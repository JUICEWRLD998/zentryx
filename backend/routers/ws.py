"""
WebSocket router — Phase 3 + DB-backed trade feed.

Exposes:
  WS  /ws/feed                          — live trade broadcast to frontend clients
  GET /api/tokens/{address}/mini-report — on-demand token mini-report (REST)
  GET /api/trades                       — recent trade events from DB (feed reconstruction)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import db
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from models.schemas import TokenMiniReport
from services.enrichment import build_mini_report
from services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])


@router.websocket("/ws/feed")
async def ws_feed(websocket: WebSocket) -> None:
    """
    Live feed endpoint.
    Frontend connects here to receive a stream of enriched trade events
    as JSON objects whenever a tracked wallet makes a move.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS feed error: %s", exc)
    finally:
        await manager.disconnect(websocket)


@router.get("/api/tokens/{address}/mini-report", response_model=TokenMiniReport)
async def token_mini_report(address: str) -> TokenMiniReport:
    """
    REST endpoint to fetch a token mini-report on demand.
    Used by the frontend slide-over when a user clicks a trade card.
    """
    return await build_mini_report(address)


@router.get("/api/trades")
async def recent_trades(
    limit: int = Query(default=50, ge=1, le=200),
    hours: int = Query(default=24, ge=1, le=720, description="How many hours back to fetch"),
) -> dict:
    """
    Return recent trade events from PostgreSQL for feed reconstruction.
    Used by the frontend to pre-populate the live feed on page load.
    Gracefully returns an empty list when DB is unavailable.
    """
    if not db.is_available():
        return {"trades": [], "db_available": False}

    from sqlalchemy import select
    from db import trade_event_table, wallet_table, get_session

    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    async with get_session() as session:
        result = await session.execute(
            select(trade_event_table)
            .where(trade_event_table.c.timestamp >= since)
            .order_by(trade_event_table.c.timestamp.desc())
            .limit(limit)
        )
        trades = result.fetchall()

    return {
        "db_available": True,
        "trades": [
            {
                "id": t.id,
                "signature": t.signature,
                "wallet_address": None,
                "wallet_label": t.wallet_label,
                "token_address": t.token_address,
                "token_symbol": t.token_symbol,
                "side": t.side,
                "usd_value": t.usd_value,
                "timestamp": t.timestamp.isoformat(),
                "security_score": t.security_score,
                "is_honeypot": t.is_honeypot,
                "smart_money_flag": t.smart_money_flag,
                "momentum_24h": t.momentum_24h,
                "holder_count": t.holder_count,
                "buy_sell_ratio": t.buy_sell_ratio,
                "liquidity_usd": t.liquidity_usd,
            }
            for t in trades
        ],
    }
