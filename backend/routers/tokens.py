"""
Token intelligence routes — Day 4.

GET /api/tokens/{address}/ohlcv          — OHLCV candles (1D / 7D / 30D)
GET /api/tokens/{address}/whale-buys     — Tracked whale BUY events for this token
GET /api/movers                          — Top gainers and losers by 24h price change
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

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


def _normalize_security_flags(sec: dict) -> dict:
    """Normalize token_security fields for frontend consumption."""
    top10 = sec.get("top10HolderPercent")
    if isinstance(top10, (int, float)):
        top10_pct = round(float(top10) * 100, 1)
    else:
        top10_pct = None

    risk_raw = sec.get("riskScore")
    risk_score = float(risk_raw) if isinstance(risk_raw, (int, float, str)) and str(risk_raw).strip() else None
    security_score = None if risk_score is None else max(0.0, min(100.0, 100.0 - risk_score))

    return {
        "mintable": bool(sec.get("mintable")),
        "freezeable": bool(sec.get("freezeable")),
        "mutable_metadata": bool(sec.get("mutableMetadata")),
        "transfer_fee": bool(sec.get("transferFeeEnable")),
        "top10_holder_pct": top10_pct,
        "risk_score": risk_score,
        "security_score": security_score,
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


# ── Token overview ─────────────────────────────────────────────────────────────

@router.get("/tokens/{address}/overview")
async def get_token_overview_route(address: str) -> dict:
    """
    Returns full Birdeye token overview for the given address.
    Fields match the BirdeyeToken shape used by AlphaScope.
    """
    try:
        raw, security_raw = await asyncio.gather(
            birdeye.get_token_overview(address),
            birdeye.get_token_security(address),
        )
    except Exception as exc:
        logger.warning("Token overview fetch failed for %s: %s", address[:8], exc)
        raise HTTPException(502, "Failed to fetch token data from Birdeye")

    data = (raw or {}).get("data") or {}
    sec_data = (security_raw or {}).get("data") or {}
    sec = _normalize_security_flags(sec_data)
    if not data:
        raise HTTPException(404, "Token not found or not yet indexed")

    return {
        "address":               address,
        "symbol":                data.get("symbol", "?"),
        "name":                  data.get("name", "Unknown"),
        "logoURI":               data.get("logoURI") or data.get("logo_uri") or "",
        "price":                 data.get("price") or 0,
        "priceChange24hPercent": data.get("priceChange24hPercent") or data.get("price24hChangePercent") or 0,
        "v24hUSD":               data.get("v24hUSD") or data.get("volume24hUSD") or 0,
        "v24hChangePercent":     data.get("v24hChangePercent") or data.get("volume24hChangePercent") or 0,
        "mc":                    data.get("mc") or data.get("marketCap") or data.get("marketcap") or 0,
        "realMc":                data.get("realMc") or data.get("fdv") or 0,
        "liquidity":             data.get("liquidity") or 0,
        "holder":                data.get("holder") or 0,
        "supply":                data.get("supply") or data.get("totalSupply") or 0,
        "circulatingSupply":     data.get("circulatingSupply") or 0,
        "lastTradeUnixTime":     data.get("lastTradeUnixTime") or 0,
        "securityScore":         sec.get("security_score"),
        "securityFlags": {
            "mintable": sec.get("mintable"),
            "freezeable": sec.get("freezeable"),
            "mutableMetadata": sec.get("mutable_metadata"),
            "transferFee": sec.get("transfer_fee"),
            "top10HolderPct": sec.get("top10_holder_pct"),
        },
    }


@router.get("/tokens/{address}/insight")
async def get_token_ai_insight(address: str) -> dict:
    """Return a Groq-generated token insight paragraph for the token detail page."""
    try:
        raw, security_raw = await asyncio.gather(
            birdeye.get_token_overview(address),
            birdeye.get_token_security(address),
        )
    except Exception as exc:
        logger.warning("Token insight fetch failed for %s: %s", address[:8], exc)
        raise HTTPException(502, "Failed to fetch token data for AI insight")

    data = (raw or {}).get("data") or {}
    sec_data = (security_raw or {}).get("data") or {}
    if not data:
        raise HTTPException(404, "Token not found or not yet indexed")

    from services.gemini import analyse_token_overview

    sec = _normalize_security_flags(sec_data)
    insight = await analyse_token_overview(
        token_symbol=data.get("symbol") or address[:8],
        token_address=address,
        price=float(data.get("price") or 0),
        price_change_24h=float(data.get("priceChange24hPercent") or data.get("price24hChangePercent") or 0),
        volume_24h_usd=float(data.get("v24hUSD") or data.get("volume24hUSD") or 0),
        market_cap=float(data.get("mc") or data.get("marketCap") or data.get("marketcap") or 0),
        liquidity=float(data.get("liquidity") or 0),
        holders=int(data.get("holder") or 0),
        security_score=sec.get("security_score"),
        flags={
            "mintable": sec.get("mintable"),
            "freezeable": sec.get("freezeable"),
            "mutable_metadata": sec.get("mutable_metadata"),
            "transfer_fee": sec.get("transfer_fee"),
            "top10_holder_pct": sec.get("top10_holder_pct"),
        },
    )

    return {"insight": insight, "source": "groq" if insight else "rule-based"}


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


# ── Smart Money Heatmap ─────────────────────────────────────────────────────

@router.get("/heatmap")
async def get_heatmap() -> dict:
    """
    Smart Money Heatmap — net buy/sell USD per token per time bucket.
    Tries 6h window with 1h buckets; falls back to 24h / 4h buckets if sparse.

    Returns:
        tokens: [{address, symbol}]  (top 10 by activity)
        buckets: ["HH:MM", ...]      (column labels)
        cells: [[net_usd, ...], ...]  (rows=tokens, cols=buckets)
        bucket_hours: int
    """
    if not db.is_available():
        return {"tokens": [], "buckets": [], "cells": [], "bucket_hours": 1}

    from collections import defaultdict
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    WINDOWS = [
        (timedelta(hours=6),  timedelta(hours=1)),
        (timedelta(hours=24), timedelta(hours=4)),
    ]

    for window, bucket_size in WINDOWS:
        since = now - window
        num_buckets = int(window / bucket_size)

        async with get_session() as session:
            result = await session.execute(
                select(trade_event_table)
                .where(trade_event_table.c.timestamp >= since)
                .order_by(trade_event_table.c.timestamp.asc())
            )
            rows = result.fetchall()

        if not rows:
            continue

        token_symbols: dict[str, str] = {}
        bucket_matrix: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))

        for r in rows:
            if not r.timestamp:
                continue
            ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
            idx = int((ts - since).total_seconds() / bucket_size.total_seconds())
            idx = max(0, min(idx, num_buckets - 1))
            sign = 1 if r.side == "BUY" else -1
            bucket_matrix[r.token_address][idx] += sign * (r.usd_value or 0)
            if r.token_address not in token_symbols:
                token_symbols[r.token_address] = r.token_symbol or r.token_address[:8]

        if not bucket_matrix:
            continue

        # Top 10 tokens by total absolute activity
        top_tokens = sorted(
            token_symbols.keys(),
            key=lambda a: sum(abs(v) for v in bucket_matrix[a].values()),
            reverse=True,
        )[:10]

        buckets = [
            (since + i * bucket_size).strftime("%H:%M")
            for i in range(num_buckets)
        ]
        cells = [
            [round(bucket_matrix[addr].get(i, 0.0), 2) for i in range(num_buckets)]
            for addr in top_tokens
        ]

        return {
            "tokens": [{"address": a, "symbol": token_symbols[a]} for a in top_tokens],
            "buckets": buckets,
            "cells": cells,
            "bucket_hours": int(bucket_size.total_seconds() / 3600),
        }

    return {"tokens": [], "buckets": [], "cells": [], "bucket_hours": 1}


# ── Smart Money Overlap ─────────────────────────────────────────────────────

@router.get("/tokens/overlap")
async def get_overlap() -> list[dict]:
    """
    Returns tokens held/traded by 2+ tracked smart-money wallets, ranked by whale count.
    """
    if not db.is_available():
        return []

    from collections import defaultdict
    from services.wallet_discovery import get_tracked_wallets

    tracked = {w.address for w in get_tracked_wallets()}

    async with get_session() as session:
        result = await session.execute(
            select(
                trade_event_table.c.token_address,
                trade_event_table.c.token_symbol,
                trade_event_table.c.wallet_id,
            ).distinct()
        )
        rows = result.fetchall()

    token_wallets: dict[str, set] = defaultdict(set)
    token_symbols: dict[str, str] = {}
    for r in rows:
        if r.wallet_id in tracked:
            token_wallets[r.token_address].add(r.wallet_id)
            if r.token_address not in token_symbols and r.token_symbol:
                token_symbols[r.token_address] = r.token_symbol

    overlap = [
        {
            "address": addr,
            "symbol": token_symbols.get(addr) or addr[:8],
            "whale_count": len(wallets),
        }
        for addr, wallets in token_wallets.items()
        if len(wallets) >= 2
    ]
    overlap.sort(key=lambda x: x["whale_count"], reverse=True)
    return overlap[:20]


# ── Trending ─────────────────────────────────────────────────────────────────

@router.get("/trending")
async def get_trending() -> list[dict]:
    """
    Birdeye trending tokens ranked by editorial rank, with Zentryx smart-money
    metadata attached as supplementary fields.
    """
    try:
        raw = await birdeye.get_token_trending(
            sort_by="rank",
            sort_type="asc",
            offset=0,
            limit=20,
        )
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch trending tokens: {exc}")

    tokens = (raw.get("data") or {}).get("tokens") or []
    if not tokens:
        return []

    # Cross-reference DB for smart money activity (last 48 h)
    smart_buys: Counter[str] = Counter()
    if db.is_available():
        since = datetime.now(tz=timezone.utc) - timedelta(hours=48)
        async with get_session() as session:
            result = await session.execute(
                select(trade_event_table.c.token_address)
                .where(
                    trade_event_table.c.side == "BUY",
                    trade_event_table.c.smart_money_flag == True,  # noqa: E712
                    trade_event_table.c.timestamp >= since,
                )
            )
            smart_buys = Counter(r.token_address for r in result.fetchall())

    result_list: list[dict] = []
    for token in tokens:
        addr = token.get("address") or ""
        volume = token.get("volume24hUSD") or token.get("v24hUSD") or 0
        whale_count = smart_buys.get(addr, 0)
        smart_score = round(whale_count * 10 + math.log1p(volume), 2)
        result_list.append({
            "rank": token.get("rank") or 0,
            "address": addr,
            "symbol": token.get("symbol") or addr[:8],
            "name": token.get("name") or "",
            "logo_uri": token.get("logoURI") or "",
            "price": token.get("price") or 0,
            "price_change_24h": token.get("price24hChangePercent") or token.get("priceChange24hPercent") or 0,
            "volume_24h_usd": volume,
            "volume_change_24h": token.get("volume24hChangePercent") or token.get("v24hChangePercent") or 0,
            "liquidity": token.get("liquidity") or 0,
            "market_cap": token.get("marketcap") or token.get("marketCap") or token.get("mc") or 0,
            "smart_buy_count": whale_count,
            "smart_score": smart_score,
        })

    # Preserve API rank order; attach smart_buy_count as supplementary signal
    result_list.sort(key=lambda x: x["rank"])
    return result_list


# ── New Listings ─────────────────────────────────────────────────────────────

async def _fetch_security(address: str) -> dict:
    """Fetch token security data for a single token. Returns {} on failure."""
    try:
        raw = await birdeye.get_token_security(address)
        return (raw.get("data") or {}) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _derive_risk(sec: dict) -> str:
    """
    Derive a simple risk label from Birdeye token_security fields.

    Scoring:
      +2  freezeable mint authority active  (critical)
      +2  transfer fee enabled              (critical)
      +1  mutable metadata                  (moderate)
      +1  top-10 holders own >80% supply    (moderate)

    DANGER >= 2 points | RISKY = 1 | SAFE = 0
    """
    if not sec:
        return "UNKNOWN"
    score = 0
    if sec.get("freezeable"):
        score += 2
    if sec.get("transferFeeEnable"):
        score += 2
    if sec.get("mutableMetadata"):
        score += 1
    if (sec.get("top10HolderPercent") or 0) > 0.8:
        score += 1
    if score >= 2:
        return "DANGER"
    if score == 1:
        return "RISKY"
    return "SAFE"


@router.get("/new-listings")
async def get_new_listings_route() -> list[dict]:
    """
    Recently listed Solana tokens, enriched with security risk scoring.

    Each item includes age_hours, liquidity, risk_level (SAFE/RISKY/DANGER),
    and granular security flags for the frontend to render badges.
    Security checks are capped at ENRICH_LIMIT=15 to stay within rate limits.
    """
    try:
        raw = await birdeye.get_new_listings(limit=20, offset=0)
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch new listings: {exc}")

    # Response: data is {"items": [...]} or occasionally a direct list
    data = raw.get("data") or []
    if isinstance(data, dict):
        items: list[dict] = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    if not items:
        return []

    # Deduplicate by address (Birdeye occasionally returns the same token twice)
    seen: set[str] = set()
    unique_items: list[dict] = []
    for item in items:
        addr = item.get("address", "")
        if addr and addr not in seen:
            seen.add(addr)
            unique_items.append(item)
    items = unique_items

    now_ts = datetime.now(tz=timezone.utc).timestamp()

    # Parallel security enrichment for top 15 only (rate-limit guard)
    ENRICH_LIMIT = 15
    enrich_addrs = [item["address"] for item in items[:ENRICH_LIMIT]]
    security_results = await asyncio.gather(*[_fetch_security(a) for a in enrich_addrs])
    sec_map: dict[str, dict] = dict(zip(enrich_addrs, security_results))

    result: list[dict] = []
    for item in items:
        addr = item["address"]
        sec = sec_map.get(addr, {})

        # Parse liquidityAddedAt: "2026-05-07T07:28:05" (no tz = UTC)
        added_str = item.get("liquidityAddedAt") or ""
        age_hours = 0.0
        if added_str:
            try:
                added_dt = datetime.fromisoformat(added_str.replace("Z", "+00:00"))
                if added_dt.tzinfo is None:
                    added_dt = added_dt.replace(tzinfo=timezone.utc)
                age_hours = round((now_ts - added_dt.timestamp()) / 3600, 1)
            except Exception:
                age_hours = 0.0

        result.append({
            "address": addr,
            "symbol": item.get("symbol") or addr[:8],
            "name": item.get("name") or "",
            "logo_uri": item.get("logoURI") or "",
            "price": item.get("price") or 0,
            "volume_24h_usd": item.get("v24hUSD") or 0,
            "market_cap": item.get("mc") or 0,
            "liquidity": item.get("liquidity") or 0,
            "source": item.get("source") or "",
            "age_hours": age_hours,
            "freezeable": bool(sec.get("freezeable")),
            "mutable_metadata": bool(sec.get("mutableMetadata")),
            "transfer_fee": bool(sec.get("transferFeeEnable")),
            "top10_holder_pct": round((sec.get("top10HolderPercent") or 0) * 100, 1),
            "risk_level": _derive_risk(sec),
        })

    return result


# ── Signal Profitability ──────────────────────────────────────────────────────

@router.get("/stats/profitability")
async def get_signal_profitability() -> dict:
    """
    Returns cached signal profitability stats for tracked whale BUY signals.
    Triggers an initial compute if the cache is empty.
    """
    from services.signal_stats import get_cached_stats, calculate_signal_profitability

    cached = get_cached_stats()
    if cached is None:
        if db.is_available():
            await calculate_signal_profitability()
        cached = get_cached_stats()

    if cached is None:
        return {
            "computed_at": None,
            "total_signals": 0,
            "profitable": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "top_performers": [],
            "message": "No data yet — DB unavailable or no signals recorded.",
        }
    return cached
