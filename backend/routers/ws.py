"""
WebSocket router — Phase 3.

Exposes GET /api/tokens/{address}/mini-report (REST, Phase 5 preview)
and WS /ws/feed for live trade broadcasts to frontend clients.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
        # Keep the connection open; we only push data server→client.
        # We still await messages to detect disconnects.
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
