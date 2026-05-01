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
    from services.wallet_discovery import discover_wallets  # local import to avoid circular

    asyncio.create_task(discover_wallets())
    return {"message": "Wallet discovery triggered."}
