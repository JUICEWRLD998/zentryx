"""
GET /api/wallets — leaderboard endpoint.
GET /api/wallets/{address} — single wallet detail.
GET /api/wallets/{address}/history — historical snapshots for charting.

Leaderboard is served from in-memory cached discovery data (free-tier safe).
Snapshot history is fetched from PostgreSQL when available.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import uuid

from sqlalchemy import select

import db
from db import wallet_table, wallet_snapshot_table, get_session
from fastapi import APIRouter, Query

from models.schemas import LeaderboardEntry
from services import birdeye
from services import wallet_discovery as wd
from services.wallet_discovery import get_tracked_wallets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["wallets"])


@router.get("/wallets", response_model=list[LeaderboardEntry])
async def list_wallets() -> list[LeaderboardEntry]:
    """
    Return the leaderboard from cached wallet-discovery data.
    Metrics are refreshed weekly by the APScheduler cron job (and on startup).
    This path makes zero additional Birdeye calls — free-tier safe.
    """
    tracked = get_tracked_wallets()
    return [
        LeaderboardEntry(
            rank=rank,
            address=w.address,
            label=w.label,
            total_pnl=w.total_pnl,
            win_rate=w.win_rate,
            trade_count=w.trade_count,
        )
        for rank, w in enumerate(tracked, start=1)
    ]


@router.get("/wallets/{address}/history")
async def wallet_history(
    address: str,
    days: int = Query(default=7, ge=1, le=30, description="Number of past days to return"),
) -> dict:
    """
    Return historical WalletSnapshot rows for a wallet, for charting.
    Defaults to 7 days, max 30 days (retention window).
    Returns an empty list when DB is unavailable (graceful degradation).
    """
    if not db.is_available():
        return {"address": address, "snapshots": []}

    since = datetime.now(tz=timezone.utc) - timedelta(days=days)

    async with get_session() as session:
        result = await session.execute(
            select(wallet_table).where(wallet_table.c.address == address)
        )
        db_wallet = result.fetchone()
    if not db_wallet:
        return {"address": address, "snapshots": []}

    async with get_session() as session:
        result = await session.execute(
            select(wallet_snapshot_table)
            .where(
                wallet_snapshot_table.c.wallet_id == db_wallet.id,
                wallet_snapshot_table.c.timestamp >= since,
            )
            .order_by(wallet_snapshot_table.c.timestamp.asc())
        )
        snapshots = result.fetchall()

    return {
        "address": address,
        "label": db_wallet.label,
        "snapshots": [
            {
                "timestamp": s.timestamp.isoformat(),
                "total_pnl": s.total_pnl,
                "realized_pnl": s.realized_pnl,
                "unrealized_pnl": s.unrealized_pnl,
                "win_rate": s.win_rate,
                "trade_count": s.trade_count,
                "net_worth_usd": s.net_worth_usd,
            }
            for s in snapshots
        ],
    }


@router.get("/wallets/{address}")
async def wallet_detail(address: str) -> dict:
    """
    Return detailed data for a single wallet.
    Fetches pnl/summary and net-worth in parallel; tolerates 401/403 on paid endpoints.
    """
    wallet = wd.tracked_wallets.get(address)

    pnl_raw, net_worth_raw = await asyncio.gather(
        birdeye.get_wallet_pnl_summary(address),
        birdeye.get_wallet_net_worth(address),
        return_exceptions=True,
    )

    pnl_data: dict = {}
    if isinstance(pnl_raw, dict):
        data_block = pnl_raw.get("data") or {}
        summary = data_block.get("summary") or {}
        pnl_block = summary.get("pnl") or {}
        counts_block = summary.get("counts") or {}
        pnl_data = {
            "realized_usd": pnl_block.get("realized_profit_usd"),
            "unrealized_usd": pnl_block.get("unrealized_usd"),
            "total_usd": pnl_block.get("total_usd"),
            "win_rate": counts_block.get("win_rate"),
            "total_trade": counts_block.get("total_trade"),
            "total_win": counts_block.get("total_win"),
            "total_loss": counts_block.get("total_loss"),
        }

    net_worth_data: dict = {}
    if isinstance(net_worth_raw, dict):
        data = net_worth_raw.get("data") or {}
        net_worth_data = {
            "total_usd": data.get("total_usd") or data.get("totalUsd"),
        }

    return {
        "address": address,
        "label": wallet.label if wallet else f"{address[:8]}...",
        "is_tracked": wallet is not None,
        "pnl": pnl_data,
        "net_worth": net_worth_data,
    }


@router.post("/wallets/discover", status_code=202)
async def trigger_discovery() -> dict:
    """Manually trigger wallet discovery (useful for testing without waiting for cron)."""
    from services.wallet_discovery import discover_wallets

    asyncio.create_task(discover_wallets())
    return {"message": "Wallet discovery triggered."}


@router.get("/wallets/{address}/portfolio")
async def wallet_portfolio(address: str) -> list[dict]:
    """
    Portfolio X-Ray — current token holdings for a wallet.
    Each item: address, symbol, name, logo_uri, amount, price_usd, usd_value, allocation_pct
    """
    from fastapi import HTTPException
    try:
        raw = await birdeye.get_wallet_portfolio(address)
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch portfolio: {exc}")

    items = (raw.get("data") or {}).get("items") or []
    # Filter dust (< $0.01) and sort by value descending
    items = [i for i in items if (i.get("valueUsd") or 0) >= 0.01]
    items.sort(key=lambda x: x.get("valueUsd") or 0, reverse=True)

    total_usd = sum(i.get("valueUsd") or 0 for i in items)

    return [
        {
            "address": item["address"],
            "symbol": item.get("symbol") or item["address"][:8],
            "name": item.get("name") or "",
            "logo_uri": item.get("logoURI") or item.get("icon") or "",
            "amount": item.get("uiAmount") or 0,
            "price_usd": item.get("priceUsd") or 0,
            "usd_value": item.get("valueUsd") or 0,
            "allocation_pct": round(
                (item.get("valueUsd") or 0) / total_usd * 100, 1
            ) if total_usd > 0 else 0,
        }
        for item in items
    ]


# ── Balance Change (endpoint 6) ───────────────────────────────────────────────

@router.get("/wallets/{address}/balance-change")
async def wallet_balance_change(address: str) -> dict:
    """
    24H and 7D balance delta for a wallet.
    Uses Birdeye endpoint 6 — /wallet/v2/balance-change.
    """
    from fastapi import HTTPException
    try:
        raw = await birdeye.get_wallet_balance_change(address)
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch balance change: {exc}")

    data = raw.get("data") or {}

    return {
        "address": address,
        "change_24h_usd": data.get("change24h") or data.get("changeUsd24h") or data.get("netChange24hUsd") or 0,
        "change_7d_usd":  data.get("change7d")  or data.get("changeUsd7d")  or data.get("netChange7dUsd")  or 0,
        "change_24h_pct": data.get("change24hPercent") or data.get("pctChange24h") or 0,
        "change_7d_pct":  data.get("change7dPercent")  or data.get("pctChange7d")  or 0,
        "current_usd":    data.get("totalUsd") or data.get("netWorth") or 0,
    }


# ── Net Worth Details (endpoint 4) ────────────────────────────────────────────

@router.get("/wallets/{address}/net-worth-details")
async def wallet_net_worth_details(address: str) -> dict:
    """
    Full asset class breakdown — not just a total net worth number.
    Uses Birdeye endpoint 4 — /wallet/v2/net-worth-details.
    """
    from fastapi import HTTPException
    try:
        raw = await birdeye.get_wallet_net_worth_details(address)
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch net worth details: {exc}")

    data = raw.get("data") or {}
    items: list[dict] = data.get("items") or data.get("assets") or []

    total_usd = sum((i.get("valueUsd") or i.get("usdValue") or 0) for i in items)

    categories: dict[str, float] = {}
    breakdown: list[dict] = []
    for item in items:
        symbol = item.get("symbol") or item.get("name") or "Unknown"
        value = float(item.get("valueUsd") or item.get("usdValue") or 0)
        category = item.get("type") or item.get("assetType") or "token"
        categories[category] = categories.get(category, 0) + value
        breakdown.append({
            "symbol": symbol,
            "category": category,
            "value_usd": value,
            "allocation_pct": round(value / total_usd * 100, 1) if total_usd > 0 else 0,
            "logo_uri": item.get("logoURI") or item.get("icon") or "",
        })

    breakdown.sort(key=lambda x: x["value_usd"], reverse=True)

    return {
        "address": address,
        "total_usd": float(data.get("totalUsd") or data.get("total_usd") or total_usd),
        "categories": [
            {"category": k, "value_usd": round(v, 2)}
            for k, v in sorted(categories.items(), key=lambda x: x[1], reverse=True)
        ],
        "breakdown": breakdown[:20],
    }


# ── Activity Timeline (endpoint 7) ────────────────────────────────────────────

@router.get("/wallets/{address}/activity")
async def wallet_activity(
    address: str,
    limit: int = 20,
) -> list[dict]:
    """
    Last N transactions for a wallet — type, amount, token, timestamp.
    Uses Birdeye endpoint 7 — /v1/wallet/tx_list.
    """
    from fastapi import HTTPException
    try:
        raw = await birdeye.get_wallet_tx_list(address, limit=min(limit, 50))
    except Exception as exc:
        raise HTTPException(502, f"Failed to fetch wallet activity: {exc}")

    items: list[dict] = (raw.get("data") or {}).get("items") or (raw.get("data") or [])
    if isinstance(items, dict):
        items = items.get("items") or []

    result: list[dict] = []
    for tx in items:
        result.append({
            "signature": tx.get("txHash") or tx.get("signature") or "",
            "type": tx.get("type") or tx.get("txType") or "unknown",
            "side": tx.get("side") or ("BUY" if (tx.get("type") or "").upper() == "SWAP" else ""),
            "token_address": tx.get("tokenAddress") or tx.get("address") or "",
            "token_symbol": tx.get("tokenSymbol") or tx.get("symbol") or "",
            "amount": tx.get("uiAmount") or tx.get("amount") or 0,
            "value_usd": tx.get("valueUsd") or tx.get("usdValue") or 0,
            "timestamp": tx.get("blockUnixTime") or tx.get("timestamp") or 0,
            "status": tx.get("status") or "confirmed",
        })

    return result
