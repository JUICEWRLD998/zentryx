"""
GET /api/wallets — leaderboard endpoint.
GET /api/wallets/{address} — single wallet detail.

Serves leaderboard from in-memory cached discovery data (free-tier safe).
No calls to paid endpoints (/wallet/v2/pnl/multiple) at request time.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

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
