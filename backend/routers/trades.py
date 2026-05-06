"""
Paper trade + price alert API routes.

POST   /api/trades               — open a paper trade
GET    /api/trades               — list trades for a Telegram user
PATCH  /api/trades/{id}/close    — manually close a trade

POST   /api/alerts               — create a price alert
GET    /api/alerts               — list active alerts for a Telegram user
DELETE /api/alerts/{id}          — cancel an alert
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update as sa_update

import db
from db import paper_trade_table, price_alert_table, get_session
from services import birdeye

router = APIRouter(prefix="/api", tags=["trades"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OpenTradeRequest(BaseModel):
    telegram_user_id: int
    token_address: str
    symbol: str | None = None
    side: str = "BUY"
    tp_pct: float | None = Field(default=None, description="Take-profit % (e.g. 40.0)")
    sl_pct: float | None = Field(default=None, description="Stop-loss % (e.g. -15.0)")
    position_size_usd: float | None = None
    entry_price: float | None = Field(default=None, description="Override auto-fetch entry price")


class CloseTradeRequest(BaseModel):
    exit_price: float | None = None


class CreateAlertRequest(BaseModel):
    telegram_user_id: int
    token_address: str
    symbol: str | None = None
    target_price: float
    direction: str = Field(description="'above' or 'below'")


# ---------------------------------------------------------------------------
# Paper trade routes
# ---------------------------------------------------------------------------

@router.post("/trades", status_code=201)
async def open_trade(req: OpenTradeRequest) -> dict:
    """Open a new paper trade at the current Birdeye price (or a provided override)."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(400, "side must be BUY or SELL")

    # Fetch current price if not supplied
    entry_price = req.entry_price
    if entry_price is None:
        try:
            raw = await birdeye.get_token_price(req.token_address)
            entry_price = float((raw.get("data") or {}).get("value") or 0)
        except Exception:
            raise HTTPException(502, "Failed to fetch current price from Birdeye")
        if not entry_price:
            raise HTTPException(400, "Could not resolve entry price — supply entry_price manually")

    trade_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    async with get_session() as session:
        await session.execute(
            paper_trade_table.insert().values(
                id=trade_id,
                telegram_user_id=req.telegram_user_id,
                token_address=req.token_address,
                symbol=req.symbol or req.token_address[:8],
                side=req.side.upper(),
                entry_price=entry_price,
                entry_time=now,
                tp_pct=req.tp_pct,
                sl_pct=req.sl_pct,
                position_size_usd=req.position_size_usd,
                status="open",
                exit_price=None,
                exit_time=None,
                pnl_pct=None,
                close_reason=None,
                created_at=now,
            )
        )

    return {
        "id": trade_id,
        "status": "open",
        "token_address": req.token_address,
        "symbol": req.symbol or req.token_address[:8],
        "side": req.side.upper(),
        "entry_price": entry_price,
        "tp_pct": req.tp_pct,
        "sl_pct": req.sl_pct,
        "position_size_usd": req.position_size_usd,
        "entry_time": now.isoformat(),
    }


@router.get("/trades")
async def list_trades(
    telegram_user_id: int = Query(...),
    status: str | None = Query(default=None, description="Filter: open / closed / all"),
) -> list[dict]:
    """List paper trades for a Telegram user."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    stmt = select(paper_trade_table).where(
        paper_trade_table.c.telegram_user_id == telegram_user_id
    )
    if status and status != "all":
        stmt = stmt.where(paper_trade_table.c.status == status)
    stmt = stmt.order_by(paper_trade_table.c.created_at.desc()).limit(50)

    async with get_session() as session:
        result = await session.execute(stmt)
        rows = result.fetchall()

    return [
        {
            "id": r.id,
            "token_address": r.token_address,
            "symbol": r.symbol,
            "side": r.side,
            "entry_price": r.entry_price,
            "entry_time": r.entry_time.isoformat() if r.entry_time else None,
            "tp_pct": r.tp_pct,
            "sl_pct": r.sl_pct,
            "position_size_usd": r.position_size_usd,
            "status": r.status,
            "exit_price": r.exit_price,
            "exit_time": r.exit_time.isoformat() if r.exit_time else None,
            "pnl_pct": r.pnl_pct,
            "close_reason": r.close_reason,
        }
        for r in rows
    ]


@router.patch("/trades/{trade_id}/close")
async def close_trade(trade_id: str, req: CloseTradeRequest) -> dict:
    """Manually close a paper trade. Fetches live price if exit_price not given."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    async with get_session() as session:
        result = await session.execute(
            select(paper_trade_table).where(paper_trade_table.c.id == trade_id)
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(404, "Trade not found")
    if row.status != "open":
        raise HTTPException(400, f"Trade is already {row.status}")

    exit_price = req.exit_price
    if exit_price is None:
        try:
            raw = await birdeye.get_token_price(row.token_address)
            exit_price = float((raw.get("data") or {}).get("value") or 0)
        except Exception:
            raise HTTPException(502, "Failed to fetch exit price")

    pnl_pct = round(((exit_price - row.entry_price) / row.entry_price) * 100, 2)
    if row.side == "SELL":
        pnl_pct = -pnl_pct

    now = datetime.now(tz=timezone.utc)
    async with get_session() as session:
        await session.execute(
            sa_update(paper_trade_table)
            .where(paper_trade_table.c.id == trade_id)
            .values(
                status="closed",
                exit_price=exit_price,
                exit_time=now,
                pnl_pct=pnl_pct,
                close_reason="manual",
            )
        )

    return {
        "id": trade_id,
        "status": "closed",
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "close_reason": "manual",
        "exit_time": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Price alert routes
# ---------------------------------------------------------------------------

@router.post("/alerts", status_code=201)
async def create_alert(req: CreateAlertRequest) -> dict:
    """Create a price alert that fires via Telegram when the target price is crossed."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    if req.direction not in ("above", "below"):
        raise HTTPException(400, "direction must be 'above' or 'below'")

    alert_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    async with get_session() as session:
        await session.execute(
            price_alert_table.insert().values(
                id=alert_id,
                telegram_user_id=req.telegram_user_id,
                token_address=req.token_address,
                symbol=req.symbol or req.token_address[:8],
                target_price=req.target_price,
                direction=req.direction,
                created_at=now,
                triggered_at=None,
                status="active",
            )
        )

    return {
        "id": alert_id,
        "token_address": req.token_address,
        "symbol": req.symbol or req.token_address[:8],
        "target_price": req.target_price,
        "direction": req.direction,
        "status": "active",
    }


@router.get("/alerts")
async def list_alerts(telegram_user_id: int = Query(...)) -> list[dict]:
    """List active price alerts for a Telegram user."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    async with get_session() as session:
        result = await session.execute(
            select(price_alert_table)
            .where(
                price_alert_table.c.telegram_user_id == telegram_user_id,
                price_alert_table.c.status == "active",
            )
            .order_by(price_alert_table.c.created_at.desc())
        )
        rows = result.fetchall()

    return [
        {
            "id": r.id,
            "token_address": r.token_address,
            "symbol": r.symbol,
            "target_price": r.target_price,
            "direction": r.direction,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.delete("/alerts/{alert_id}", status_code=204)
async def cancel_alert(alert_id: str) -> None:
    """Cancel a price alert."""
    if not db.is_available():
        raise HTTPException(503, "Database not available")

    async with get_session() as session:
        result = await session.execute(
            select(price_alert_table).where(price_alert_table.c.id == alert_id)
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(404, "Alert not found")

    async with get_session() as session:
        await session.execute(
            sa_update(price_alert_table)
            .where(price_alert_table.c.id == alert_id)
            .values(status="cancelled")
        )
