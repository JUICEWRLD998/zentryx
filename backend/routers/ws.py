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

    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    trades = await db.prisma.tradeevent.find_many(
        where={"timestamp": {"gte": since}},
        order={"timestamp": "desc"},
        take=limit,
        include={"wallet": True},
    )

    return {
        "db_available": True,
        "trades": [
            {
                "id": t.id,
                "signature": t.signature,
                "wallet_address": t.wallet.address if t.wallet else None,
                "wallet_label": t.walletLabel,
                "token_address": t.tokenAddress,
                "token_symbol": t.tokenSymbol,
                "side": t.side,
                "usd_value": t.usdValue,
                "timestamp": t.timestamp.isoformat(),
                "security_score": t.securityScore,
                "is_honeypot": t.isHoneypot,
                "smart_money_flag": t.smartMoneyFlag,
                "momentum_24h": t.momentum24h,
                "holder_count": t.holderCount,
                "buy_sell_ratio": t.buySellRatio,
                "liquidity_usd": t.liquidityUsd,
            }
            for t in trades
        ],
    }
