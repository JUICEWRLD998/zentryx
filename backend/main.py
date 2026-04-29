"""
Zentryx FastAPI application entry point.

Startup sequence (via lifespan):
  1. Load .env
  2. Start APScheduler (weekly wallet discovery)
  3. Run initial wallet discovery so the app has data immediately
  4. Start Birdeye WebSocket listener in background task
  5. Send Telegram startup notification
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # Load backend/.env before any service initializes

import db
from routers.wallets import router as wallets_router
from routers.ws import router as ws_router
from scheduler import scheduler
from services.birdeye_ws import run_birdeye_ws
from services.enrichment import process_trade_event
from services.polling_worker import run_polling_worker
from services.telegram import run_bot_command_loop, send_startup_message
from services.wallet_discovery import discover_wallets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_ws_task: asyncio.Task | None = None
_poll_task: asyncio.Task | None = None
_bot_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_task, _poll_task
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Zentryx backend starting up...")

    # Connect to PostgreSQL (gracefully skips if DATABASE_URL not set)
    await db.connect()

    scheduler.start()
    logger.info("Scheduler started. Running initial wallet discovery...")
    await discover_wallets()

    # Start Birdeye WebSocket listener as a background task (gracefully degrades on 403)
    _ws_task = asyncio.create_task(run_birdeye_ws(process_trade_event))
    logger.info("Birdeye WebSocket listener started.")

    # Start REST polling fallback — feeds live data when WS is unavailable
    _poll_task = asyncio.create_task(run_polling_worker(process_trade_event))
    logger.info("REST polling fallback started.")

    # Start Telegram bot command loop — listens for /start, /wallets, /help
    _bot_task = asyncio.create_task(run_bot_command_loop())
    logger.info("Telegram bot command loop started.")

    # Telegram startup ping
    await send_startup_message()

    logger.info("Startup complete.")
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
    scheduler.shutdown(wait=False)
    await db.disconnect()
    logger.info("Zentryx backend shut down.")


app = FastAPI(
    title="Zentryx API",
    description="Copy-Trading Intelligence Terminal — Solana whale tracking via Birdeye.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and Vercel deploy
_allowed_origins = [
    "http://localhost:3000",
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(wallets_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    """Quick liveness check."""
    return {"status": "ok", "service": "zentryx-api", "version": "0.2.0"}
