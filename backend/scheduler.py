"""
APScheduler job that re-runs wallet discovery every Sunday at midnight.
The scheduler is started and stopped via the FastAPI lifespan hook in main.py.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.wallet_discovery import discover_wallets

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

scheduler.add_job(
    discover_wallets,
    trigger="cron",
    day_of_week="sun",
    hour=0,
    minute=0,
    id="weekly_wallet_discovery",
    replace_existing=True,
)
