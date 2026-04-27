"""
Zentryx FastAPI application entry point.

Startup sequence (via lifespan):
  1. Load .env
  2. Start APScheduler (weekly wallet discovery)
  3. Run initial wallet discovery so the app has data immediately
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # Load backend/.env before any service initializes

from routers.wallets import router as wallets_router
from scheduler import scheduler
from services.wallet_discovery import discover_wallets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Zentryx backend starting up...")
    scheduler.start()
    logger.info("Scheduler started. Running initial wallet discovery...")
    await discover_wallets()
    logger.info("Startup complete.")
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    logger.info("Zentryx backend shut down.")


app = FastAPI(
    title="Zentryx API",
    description="Copy-Trading Intelligence Terminal — Solana whale tracking via Birdeye.",
    version="0.1.0",
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


@app.get("/health")
async def health() -> dict:
    """Quick liveness check."""
    return {"status": "ok", "service": "zentryx-api"}
