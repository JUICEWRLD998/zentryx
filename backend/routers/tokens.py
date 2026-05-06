"""
Token intelligence routes — Day 4.

GET /api/tokens/{address}/ohlcv          — OHLCV candles (1D / 7D / 30D)
GET /api/tokens/{address}/whale-buys     — Tracked whale BUY events for this token
GET /api/movers                          — Top gainers and losers by 24h price change
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

import db
from db import trade_event_table, get_session
from services import birdeye

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tokens"])

# ── OHLCV timeframe config ──────────────────────────────────────────────────

_TIMEFRAME_MAP = {
    "1D": ("1H",  86_400),
    "7D": ("4H",  7 * 86_400),
    "30D": ("1D", 30 * 86_400),
}


@router.get("/tokens/{address}/ohlcv")
async def get_ohlcv(
    address: str,
    timeframe: str = Query(default="7D", description="1D | 7D | 30D"),
) -> list[dict]:
    """
    Returns OHLCV candles for the given token.

    Each candle: { time, open, high, low, close, volume }
    `time` is a Unix timestamp (seconds).
    """
    if timeframe not in _TIMEFRAME_MAP:
        raise HTTPException(400, f"timeframe must be one of: {', '.join(_TIMEFRAME_MAP)}")

    birdeye_type, window_s = _TIMEFRAME_MAP[timeframe]
    now = int(time.time())
    time_from = now - window_s

    try:
        raw = await birdeye.get_token_ohlcv(
            address,
            timeframe=birdeye_type,
            time_from=time_from,
            time_to=now,
        )
    except Exception as exc:
        logger.warning("OHLCV fetch failed for %s: %s", address[:8], exc)
        raise HTTPException(502, "Failed to fetch OHLCV data from Birdeye")

    items = (raw.get("data") or {}).get("items") or []
    return [
        {
            "time": item["unixTime"],
            "open": item["o"],
            "high": item["h"],
            "low":  item["l"],
            "close": item["c"],
            "volume": item["v"],
        }
        for item in items
    ]


@router.get("/tokens/{address}/whale-buys")
async def get_whale_buys(address: str) -> list[dict]:
    """
    Returns tracked whale BUY events for this token from the DB.
    Used to render whale markers on the OHLCV chart.
    """
    if not db.is_available():
        return []

    async with get_session() as session:
        result = await session.execute(
            select(trade_event_table)
            .where(
                trade_event_table.c.token_address == address,
                trade_event_table.c.side == "BUY",
            )
            .order_by(trade_event_table.c.timestamp.desc())
            .limit(50)
        )
        rows = result.fetchall()

    return [
        {
            "time": int(r.timestamp.timestamp()),
            "usd_value": r.usd_value,
            "wallet_label": r.wallet_label or r.wallet_id[:8] if r.wallet_id else "unknown",
            "smart_money": r.smart_money_flag,
        }
        for r in rows
        if r.timestamp
    ]


# ── Movers (gainers & losers) ───────────────────────────────────────────────

async def _fetch_price_change(address: str) -> float | None:
    """Fetch 24h price change % for a single token. Returns None on failure."""
    try:
        raw = await birdeye.get_token_price(address)
        return (raw.get("data") or {}).get("priceChange24h")
    except Exception:
        return None


@router.get("/movers")
async def get_movers() -> dict:
    """
    Returns top 10 gainers and top 10 losers by 24h price change.

    Steps:
      1. Fetch top 25 tokens by v24hUSD (most liquid/active) from tokenlist.
      2. Fetch price+priceChange24h for all 25 in parallel.
      3. Sort and split into gainers (top 10) and losers (bottom 10).
    """
    try:
        raw = await birdeye.get_trending_tokens(
            sort_by="v24hUSD",
            sort_type="desc",
            offset=0,
            limit=25,
        )
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch token list: {exc}")

    tokens = (raw.get("data") or {}).get("tokens") or []
    if not tokens:
        return {"gainers": [], "losers": []}

    # Fetch price change for all in parallel
    addresses = [t["address"] for t in tokens]
    changes = await asyncio.gather(*[_fetch_price_change(a) for a in addresses])

    enriched = []
    for token, change in zip(tokens, changes):
        if change is None:
            continue
        enriched.append({
            "address": token["address"],
            "symbol": token.get("symbol") or token["address"][:8],
            "name": token.get("name") or "",
            "price": token.get("price") or 0,
            "price_change_24h": round(change, 2),
            "volume_24h_usd": token.get("v24hUSD") or 0,
            "liquidity": token.get("liquidity") or 0,
            "market_cap": token.get("mc") or 0,
            "logo_uri": token.get("logoURI") or "",
        })

    # Sort by price change
    enriched.sort(key=lambda x: x["price_change_24h"], reverse=True)

    gainers = enriched[:10]
    # Losers: bottom 10, sorted ascending (most negative first)
    losers = sorted(
        [t for t in enriched if t["price_change_24h"] < 0],
        key=lambda x: x["price_change_24h"],
    )[:10]

    return {"gainers": gainers, "losers": losers}
