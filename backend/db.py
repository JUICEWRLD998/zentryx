"""
Database layer — SQLAlchemy 2.x async (asyncpg driver).
Zero native binaries. Works on any Python 3.11+ platform including Render.

Tables are created automatically on first connect (CREATE TABLE IF NOT EXISTS).

Usage anywhere:
    import db
    if db.is_available():
        async with db.get_session() as session:
            result = await session.execute(select(db.wallet_table).where(...))
            row = result.fetchone()

Lifecycle (called from FastAPI lifespan in main.py):
    await db.connect()     # on startup
    await db.disconnect()  # on shutdown
"""
from __future__ import annotations

import logging
import os
import ssl
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float,
    Integer, MetaData, String, Table, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

logger = logging.getLogger(__name__)

_engine = None
_session_factory: async_sessionmaker | None = None
_db_available: bool = False

metadata = MetaData()

# ---------------------------------------------------------------------------
# Table definitions — column names match Prisma schema @map annotations
# ---------------------------------------------------------------------------

wallet_table = Table(
    "wallet", metadata,
    Column("id", String, primary_key=True),
    Column("address", String, unique=True, nullable=False),
    Column("label", String, nullable=False),
    Column("win_rate", Float, nullable=False),
    Column("total_pnl", Float, nullable=False),
    Column("trade_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

wallet_snapshot_table = Table(
    "wallet_snapshot", metadata,
    Column("id", String, primary_key=True),
    Column("wallet_id", String, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("total_pnl", Float, nullable=False),
    Column("realized_pnl", Float, nullable=True),
    Column("unrealized_pnl", Float, nullable=True),
    Column("win_rate", Float, nullable=False),
    Column("trade_count", Integer, nullable=False),
    Column("net_worth_usd", Float, nullable=True),
)

trade_event_table = Table(
    "trade_event", metadata,
    Column("id", String, primary_key=True),
    Column("signature", String, unique=True, nullable=False),
    Column("wallet_id", String, nullable=True),
    Column("wallet_label", String, nullable=True),
    Column("token_address", String, nullable=False),
    Column("token_symbol", String, nullable=True),
    Column("side", String, nullable=False),
    Column("usd_value", Float, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("security_score", Float, nullable=True),
    Column("is_honeypot", Boolean, nullable=True),
    Column("smart_money_flag", Boolean, nullable=False),
    Column("momentum_24h", Float, nullable=True),
    Column("holder_count", Integer, nullable=True),
    Column("buy_sell_ratio", Float, nullable=True),
    Column("liquidity_usd", Float, nullable=True),
    Column("alert_sent", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

user_watchlist_table = Table(
    "user_watchlist", metadata,
    Column("id", String, primary_key=True),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("wallet_id", String, nullable=False),
    Column("added_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("telegram_user_id", "wallet_id", name="uq_user_wallet"),
)

smart_money_cache_table = Table(
    "smart_money_cache", metadata,
    Column("id", String, primary_key=True),
    Column("token_addresses", ARRAY(String), nullable=False),
    Column("cached_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

token_enrichment_cache_table = Table(
    "token_enrichment_cache", metadata,
    Column("id", String, primary_key=True),
    Column("token_address", String, unique=True, nullable=False),
    Column("cached_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("security_score", Float, nullable=True),
    Column("is_honeypot", Boolean, nullable=True),
    Column("momentum_24h", Float, nullable=True),
    Column("holder_count", Integer, nullable=True),
    Column("buy_sell_ratio", Float, nullable=True),
    Column("liquidity_usd", Float, nullable=True),
    Column("symbol", String, nullable=True),
    Column("price", Float, nullable=True),
    Column("market_cap", Float, nullable=True),
    Column("volume_24h", Float, nullable=True),
)


async def connect() -> None:
    """Initialize async engine and create all tables if they don't exist."""
    global _engine, _session_factory, _db_available
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        logger.warning(
            "DATABASE_URL not set — running without persistence. "
            "Set DATABASE_URL in backend/.env to enable."
        )
        return

    # asyncpg requires the postgresql+asyncpg:// scheme
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # asyncpg does not accept sslmode in the URL — strip it and pass ssl via connect_args
    needs_ssl = "sslmode=require" in database_url or "sslmode=verify-full" in database_url
    for param in ("sslmode=require", "sslmode=verify-full", "sslmode=verify-ca", "sslmode=prefer"):
        database_url = database_url.replace(f"&{param}", "").replace(f"?{param}", "")
    database_url = database_url.rstrip("?&")

    connect_args: dict = {}
    if needs_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    try:
        _engine = create_async_engine(
            database_url, echo=False, pool_pre_ping=True, connect_args=connect_args
        )
        _session_factory = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        # Auto-create tables (idempotent — safe to run every startup)
        async with _engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        _db_available = True
        logger.info("Database connected.")
    except Exception as exc:
        _db_available = False
        logger.warning(
            "Database connection failed — running without persistence. "
            "Set DATABASE_URL in backend/.env to enable. Error: %s",
            exc,
        )


async def disconnect() -> None:
    """Dispose the engine gracefully on shutdown."""
    global _db_available
    _db_available = False
    if _engine:
        await _engine.dispose()
        logger.info("Database disconnected.")


def is_available() -> bool:
    """Return True if the database is connected and ready."""
    return _db_available


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session, committing on success or rolling back on error."""
    if not _session_factory:
        raise RuntimeError("Database not connected.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
