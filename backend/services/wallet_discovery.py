"""
Wallet discovery service.

Calls Birdeye endpoint 1 (gainers-losers) for the week's top performers,
gates each wallet through endpoint 2 (pnl/summary), filters to the top 15
by win rate + absolute PnL, and stores them in a module-level dict.
"""
from __future__ import annotations

import asyncio
import logging

from models.schemas import TrackedWallet
from services import birdeye

logger = logging.getLogger(__name__)

# In-memory store — address → TrackedWallet
tracked_wallets: dict[str, TrackedWallet] = {}


async def _fetch_pnl_summary(wallet_address: str) -> tuple[str, dict]:
    """Return (address, raw summary dict) for a single wallet, or (address, {}) on error."""
    try:
        data = await birdeye.get_wallet_pnl_summary(wallet_address)
        return wallet_address, data
    except Exception as exc:
        logger.warning("PnL summary failed for %s: %s", wallet_address, exc)
        return wallet_address, {}


async def discover_wallets() -> None:
    """
    Refresh the tracked wallet list.

    Steps:
      1. Fetch top 50 weekly gainers (endpoint 1).
      2. Concurrently fetch PnL summary for each (endpoint 2).
      3. Filter: win_rate >= 0.55 AND total_pnl > 0.
      4. Sort by total_pnl desc, keep top 15.
      5. Store in tracked_wallets with a human-readable label.
    """
    global tracked_wallets
    logger.info("Starting wallet discovery...")

    try:
        gainers_raw = await birdeye.get_gainers_losers(
            time_frame="1W",
            sort_by="PnL",
            sort_type="desc",
            limit=50,
        )
    except Exception as exc:
        logger.error("Failed to fetch gainers-losers: %s", exc)
        return

    # Extract wallet addresses from response
    data_block = gainers_raw.get("data") or {}
    items = data_block.get("items") or []

    if not items:
        logger.warning("No items returned from gainers-losers endpoint.")
        return

    addresses = [item.get("address") for item in items if item.get("address")]
    logger.info("Fetched %d candidate wallets, fetching PnL summaries...", len(addresses))

    # Concurrent PnL summary fetch for all candidates
    results = await asyncio.gather(*[_fetch_pnl_summary(addr) for addr in addresses])

    qualified: list[dict] = []
    for address, raw in results:
        summary_data = raw.get("data") or {}
        total_pnl = float(summary_data.get("total_pnl") or 0)
        win_rate = float(summary_data.get("win_rate") or 0)
        trade_count = int(summary_data.get("trade_count") or 0)

        # Phase 2: Relaxed filter for testing; Phase 3+ can tighten to win_rate >= 0.55
        if win_rate >= 0.40 and total_pnl > 0 and trade_count >= 5:
            qualified.append(
                {
                    "address": address,
                    "total_pnl": total_pnl,
                    "win_rate": win_rate,
                    "trade_count": trade_count,
                }
            )

    # Sort by total_pnl descending, take top 15
    qualified.sort(key=lambda x: x["total_pnl"], reverse=True)
    top15 = qualified[:15]

    new_wallets: dict[str, TrackedWallet] = {}
    for rank, wallet in enumerate(top15, start=1):
        new_wallets[wallet["address"]] = TrackedWallet(
            address=wallet["address"],
            label=f"Whale #{rank}",
            win_rate=wallet["win_rate"],
            total_pnl=wallet["total_pnl"],
            trade_count=wallet["trade_count"],
        )

    tracked_wallets = new_wallets
    logger.info("Wallet discovery complete — %d wallets tracked.", len(tracked_wallets))


def get_tracked_wallets() -> list[TrackedWallet]:
    """Return current tracked wallets as a list, ordered by label."""
    return sorted(tracked_wallets.values(), key=lambda w: w.label)
