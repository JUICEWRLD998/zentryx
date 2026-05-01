"""
Zentryx FastAPI application entry point.

Startup sequence (via lifespan):
  1. Load .env
  2. Connect to PostgreSQL
  3. Start APScheduler (weekly wallet discovery + 6-hourly snapshots)
  4. Run initial wallet discovery
  5. Start Solana RPC WebSocket listener (real-time whale trade detection)
  6. Start Telegram bot command loop
  7. Send Telegram startup notification
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
from scheduler import scheduler
from services.solana_rpc_ws import run_solana_rpc_ws
from services.enrichment import process_trade_event
from services.telegram import run_bot_command_loop, send_startup_message
from services.wallet_discovery import discover_wallets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_ws_task: asyncio.Task | None = None
_bot_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ws_task, _bot_task
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Zentryx backend starting up...")
    await db.connect()
    scheduler.start()
    logger.info("Scheduler started. Running initial wallet discovery...")
    await discover_wallets()
    _ws_task = asyncio.create_task(run_solana_rpc_ws(process_trade_event))
    logger.info("Solana RPC WebSocket listener started.")
    _bot_task = asyncio.create_task(run_bot_command_loop())
    logger.info("Telegram bot command loop started.")
    await send_startup_message()
    logger.info("Startup complete.")
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(wallets_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict:
    """Quick liveness check."""
    return {"status": "ok", "service": "zentryx-api", "version": "0.2.0"}
