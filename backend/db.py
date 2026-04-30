"""
Prisma async client — single shared instance for the entire backend.

Usage anywhere:
    from db import prisma
    await prisma.wallet.find_many(...)

Lifecycle (called from FastAPI lifespan in main.py):
    from db import connect, disconnect
    await connect()   # on startup
    await disconnect() # on shutdown

If DATABASE_URL is not set or the database is unreachable, connect() logs
a warning and sets _db_available = False. All service code should check
db.is_available() before issuing queries so the app degrades gracefully
in local dev without a database.
"""
from __future__ import annotations

import logging

from prisma import Prisma

logger = logging.getLogger(__name__)

prisma: Prisma = Prisma()
_db_available: bool = False


async def connect() -> None:
    """Connect to PostgreSQL. Tolerates missing DATABASE_URL."""
    global _db_available
    try:
        await prisma.connect()
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
    """Disconnect gracefully on shutdown."""
    global _db_available
    if prisma.is_connected():
        await prisma.disconnect()
        logger.info("Database disconnected.")
    _db_available = False


def is_available() -> bool:
    """Return True if the database is reachable and the client is connected."""
    return _db_available and prisma.is_connected()
