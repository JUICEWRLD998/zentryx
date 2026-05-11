"""
Zentryx FastAPI application entry point.

Startup sequence (via lifespan):
  1. Load .env
  2. Connect to PostgreSQL
  3. Start APScheduler (daily wallet discovery + 6-hourly snapshots)
  4. Run initial wallet discovery
  5. Start Solana RPC WebSocket listener (real-time whale trade detection)
  6. Start REST polling worker (Birdeye token tx polling — catches DEX swaps the WS misses)
  7. Start Telegram bot command loop
  8. Start price monitor
  9. Send Telegram startup notification
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent / ".env")  # Load backend/.env regardless of CWD

import db
from routers.wallets import router as wallets_router
from routers.ws import router as ws_router
from routers.trades import router as trades_router
from routers.tokens import router as tokens_router
from routers.smart_money import router as smart_money_router
from routers.analytics import router as analytics_router
from scheduler import scheduler
from services.birdeye_ws import run_birdeye_ws
from services.polling_worker import run_polling_worker
from services.enrichment import process_trade_event
from services.telegram import run_bot_command_loop, send_startup_message
from services.wallet_discovery import discover_wallets
from services.price_monitor import run_price_monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_ws_task: asyncio.Task | None = None
_polling_task: asyncio.Task | None = None
_bot_task: asyncio.Task | None = None
_monitor_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_task, _polling_task, _bot_task, _monitor_task
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Zentryx backend starting up...")
    await db.connect()
    scheduler.start()
    logger.info("Scheduler started. Running initial wallet discovery...")
    await discover_wallets()
    _ws_task = asyncio.create_task(run_birdeye_ws(process_trade_event))
    logger.info("Birdeye Premium WebSocket listener started.")
    _polling_task = asyncio.create_task(run_polling_worker(process_trade_event))
    logger.info("REST polling worker started (Birdeye token tx polling).")
    _bot_task = asyncio.create_task(run_bot_command_loop())
    logger.info("Telegram bot command loop started.")
    _monitor_task = asyncio.create_task(run_price_monitor())
    logger.info("Price monitor started.")
    await send_startup_message()
    logger.info("Startup complete.")
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────
    for task in (_ws_task, _polling_task, _bot_task, _monitor_task):
        if task and not task.done():
            task.cancel()
    await asyncio.gather(
        *[t for t in (_ws_task, _polling_task, _bot_task, _monitor_task) if t],
        return_exceptions=True,
    )
    scheduler.shutdown(wait=False)
    await db.disconnect()
    logger.info("Zentryx backend shut down.")


app = FastAPI(
    title="Zentryx API",
    description="Copy-Trading Intelligence Terminal — Solana whale tracking via Solana RPC.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and Vercel deploy
_allowed_origins = [
    "http://localhost:3000",
    "https://zentryx-sooty.vercel.app",
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(wallets_router)
app.include_router(ws_router)
app.include_router(trades_router)
app.include_router(tokens_router)
app.include_router(smart_money_router)
app.include_router(analytics_router)


@app.get("/health")
async def health() -> dict:
    """Quick liveness check."""
    return {"status": "ok", "service": "zentryx-api", "version": "0.2.0"}
