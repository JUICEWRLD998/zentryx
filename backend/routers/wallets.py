"""
GET /api/wallets — leaderboard endpoint.
GET /api/wallets/{address} — single wallet detail.

Returns the top 15 tracked wallets enriched with fresh PnL data from
Birdeye endpoint 3 (/wallet/v2/pnl/multiple).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from models.schemas import LeaderboardEntry
from services import birdeye
from services import wallet_discovery as wd
from services.wallet_discovery import get_tracked_wallets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["wallets"])


@router.get("/wallets", response_model=list[LeaderboardEntry])
async def list_wallets() -> list[LeaderboardEntry]:
    """
    Return the leaderboard of currently tracked wallets.

    Fetches fresh batch PnL data from Birdeye for all tracked addresses,
    merges with in-memory discovery data, and returns a ranked list.
    """
    tracked = get_tracked_wallets()

    if not tracked:
        return []

    addresses = [w.address for w in tracked]

    # Batch PnL fetch (endpoint 3) — one call for all wallets
    try:
        batch_raw = await birdeye.get_wallet_pnl_multiple(addresses)
        batch_items: list[dict] = batch_raw.get("data") or []
    except Exception as exc:
        logger.error("Batch PnL fetch failed: %s", exc)
        # Fall back to cached discovery data instead of erroring out
        batch_items = []

    # Index fresh data by address for O(1) lookup
    fresh_by_address: dict[str, dict] = {
        item["address"]: item for item in batch_items if item.get("address")
    }

    leaderboard: list[LeaderboardEntry] = []
    for rank, wallet in enumerate(tracked, start=1):
        fresh = fresh_by_address.get(wallet.address, {})
        leaderboard.append(
            LeaderboardEntry(
                rank=rank,
                address=wallet.address,
                label=wallet.label,
                total_pnl=float(fresh.get("total_pnl") or wallet.total_pnl),
                win_rate=float(fresh.get("win_rate") or wallet.win_rate),
                trade_count=int(fresh.get("trade_count") or wallet.trade_count),
            )
        )

    return leaderboard


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
