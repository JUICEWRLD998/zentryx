"""
Wallet snapshot service — 6-hour historical metrics capture.

Reads currently tracked wallets (in-memory from wallet_discovery),
calls Birdeye for fresh PnL + net worth, and persists WalletSnapshot
rows to PostgreSQL for charting/analytics.

Also owns the daily TTL cleanup job that deletes trade_event rows
older than 30 days to enforce the rolling-window retention policy.

Both functions are registered as APScheduler jobs in scheduler.py.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import db
from services import birdeye

logger = logging.getLogger(__name__)

_INTER_REQUEST_DELAY = 2.0  # seconds between Birdeye calls (free-tier rate limit)


async def take_wallet_snapshots() -> None:
    """
    Fetch fresh PnL and net worth for every tracked wallet, then persist
    a WalletSnapshot row. Called every 6 hours by APScheduler.

    Birdeye calls:
      - get_wallet_pnl_summary (endpoint 2) — 1 CU per wallet
      - get_wallet_net_worth   (endpoint 5) — 1 CU per wallet
    Total: ~2 CU × 15 wallets = ~30 CU per run, 4×/day = ~120 CU/day
    """
    if not db.is_available():
        logger.debug("Snapshot job skipped — database not connected.")
        return

    from services.wallet_discovery import tracked_wallets  # live state

    wallets = list(tracked_wallets.values())
    if not wallets:
        logger.warning("Snapshot job: no tracked wallets — skipping.")
        return

    logger.info("Snapshotting metrics for %d wallets...", len(wallets))
    snapped = 0

    for wallet in wallets:
        await asyncio.sleep(_INTER_REQUEST_DELAY)
        try:
            # ── PnL summary ──────────────────────────────────────────────
            pnl_raw = await birdeye.get_wallet_pnl_summary(wallet.address)
            data_block = pnl_raw.get("data") or {}
            summary = data_block.get("summary") or {}
            pnl_block = summary.get("pnl") or {}
            counts_block = summary.get("counts") or {}

            total_pnl = float(
                pnl_block.get("realized_profit_usd")
                or pnl_block.get("total_usd")
                or wallet.total_pnl
            )
            realized_pnl = float(
                pnl_block.get("realized_usd") or pnl_block.get("realized_profit_usd") or 0
            ) or None
            unrealized_pnl = float(pnl_block.get("unrealized_usd") or 0) or None
            win_rate = float(counts_block.get("win_rate") or wallet.win_rate)
            trade_count = int(
                counts_block.get("total_trade")
                or counts_block.get("total_trading")
                or wallet.trade_count
            )

            # ── Net worth ────────────────────────────────────────────────
            net_worth_usd: float | None = None
            await asyncio.sleep(1.0)
            try:
                nw_raw = await birdeye.get_wallet_net_worth(wallet.address)
                nw_data = nw_raw.get("data") or {}
                nw_val = nw_data.get("total_usd") or nw_data.get("totalUsd")
                if nw_val is not None:
                    net_worth_usd = float(nw_val)
            except Exception as exc:
                logger.debug("Net worth fetch failed for %s: %s", wallet.address[:8], exc)

            # ── Resolve DB wallet record ─────────────────────────────────
            db_wallet = await db.prisma.wallet.find_unique(
                where={"address": wallet.address}
            )
            if not db_wallet:
                logger.warning(
                    "Snapshot: wallet %s not in DB — skipping.", wallet.address[:8]
                )
                continue

            await db.prisma.walletsnapshot.create(
                data={
                    "walletId": db_wallet.id,
                    "totalPnl": total_pnl,
                    "realizedPnl": realized_pnl,
                    "unrealizedPnl": unrealized_pnl,
                    "winRate": win_rate,
                    "tradeCount": trade_count,
                    "netWorthUsd": net_worth_usd,
                }
            )
            snapped += 1
            logger.info(
                "Snapshot saved: %s | pnl=%.2f | win=%.2f | worth=%s",
                wallet.label,
                total_pnl,
                win_rate,
                f"${net_worth_usd:,.0f}" if net_worth_usd else "N/A",
            )

        except Exception as exc:
            logger.warning("Snapshot failed for %s: %s", wallet.address[:8], exc)

    logger.info("Snapshot job complete — %d/%d saved.", snapped, len(wallets))


async def cleanup_old_trades() -> None:
    """
    Delete TradeEvent rows older than 30 days. Called daily at 03:00 UTC
    by APScheduler to enforce the rolling-window retention policy.
    """
    if not db.is_available():
        logger.debug("TTL cleanup skipped — database not connected.")
        return

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
    try:
        count = await db.prisma.tradeevent.delete_many(
            where={"createdAt": {"lt": cutoff}}
        )
        logger.info("TTL cleanup: deleted %d trade events older than 30 days.", count)
    except Exception as exc:
        logger.warning("TTL cleanup (trades) failed: %s", exc)

    # Purge expired token enrichment cache rows
    now = datetime.now(tz=timezone.utc)
    try:
        count = await db.prisma.tokenenrichmentcache.delete_many(
            where={"expiresAt": {"lt": now}}
        )
        if count:
            logger.info("TTL cleanup: deleted %d expired token enrichment cache rows.", count)
    except Exception as exc:
        logger.warning("TTL cleanup (enrichment cache) failed: %s", exc)
