"""
APScheduler jobs:
  1. Weekly wallet discovery — every Sunday at midnight UTC
  2. 6-hour wallet snapshots — PnL + net worth for historical charting
  3. Daily TTL cleanup — delete trade_event rows older than 30 days at 03:00 UTC

The scheduler is started and stopped via the FastAPI lifespan hook in main.py.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.wallet_discovery import discover_wallets
from services.snapshot import take_wallet_snapshots, cleanup_old_trades

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Job 1 — Weekly whale discovery (unchanged)
scheduler.add_job(
    discover_wallets,
    trigger="cron",
    day_of_week="sun",
    hour=0,
    minute=0,
    id="weekly_wallet_discovery",
    replace_existing=True,
)

# Job 2 — Every 6 hours: snapshot PnL + net worth for all tracked wallets
scheduler.add_job(
    take_wallet_snapshots,
    trigger="interval",
    hours=6,
    id="wallet_snapshots",
    replace_existing=True,
)

# Job 3 — Daily at 03:00 UTC: delete trade events older than 30 days
scheduler.add_job(
    cleanup_old_trades,
    trigger="cron",
    hour=3,
    minute=0,
    id="trade_ttl_cleanup",
    replace_existing=True,
)

