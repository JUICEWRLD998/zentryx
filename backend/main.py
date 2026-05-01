"""
Zentryx FastAPI application entry point.

The web service only handles HTTP/WebSocket API traffic.
All background monitoring (Solana RPC listener, Telegram bot, Scheduler)
runs in the dedicated background worker (worker.py).
"""
from __future__ import annotations

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("Zentryx API starting up...")
    await db.connect()
    logger.info("Startup complete.")
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────
    await db.disconnect()
    logger.info("Zentryx API shut down.")


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
