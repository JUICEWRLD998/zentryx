"""
Price monitor — background task that runs every 2 minutes.

Checks all open paper trades and active price alerts against
the current Birdeye price (/defi/price). When a target is hit:
  - Updates the DB row
  - Sends a Telegram DM to the user

Runs as an asyncio Task started in the FastAPI lifespan (main.py).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update as sa_update

import db
from db import paper_trade_table, price_alert_table, get_session
from services import birdeye

logger = logging.getLogger(__name__)

POLL_INTERVAL_S: int = 120  # 2 minutes


async def _send_dm(telegram_user_id: int, text: str) -> None:
    """Send a Telegram DM to a specific user (non-blocking, ignores errors)."""
    try:
        from telegram import Bot
        import os
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return
        bot = Bot(token=token)
        await bot.send_message(
            chat_id=telegram_user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.debug("Price monitor DM failed for user %s: %s", telegram_user_id, exc)


async def _get_price(token_address: str) -> float | None:
    """Fetch current price from Birdeye, return None on failure."""
    try:
        raw = await birdeye.get_token_price(token_address)
        value = (raw.get("data") or {}).get("value")
        return float(value) if value is not None else None
    except Exception as exc:
        logger.debug("Price fetch failed for %s: %s", token_address[:8], exc)
        return None


async def _check_paper_trades(price_cache: dict[str, float]) -> None:
    """Scan open paper trades and close any that hit TP or SL."""
    if not db.is_available():
        return

    async with get_session() as session:
        result = await session.execute(
            select(paper_trade_table).where(paper_trade_table.c.status == "open")
        )
        open_trades = result.fetchall()

    if not open_trades:
        return

    for trade in open_trades:
        token = trade.token_address

        # Use cached price if already fetched this cycle
        if token not in price_cache:
            price = await _get_price(token)
            if price is None:
                continue
            price_cache[token] = price
        price = price_cache[token]

        entry = trade.entry_price
        if not entry:
            continue

        pnl_pct = ((price - entry) / entry) * 100
        if trade.side == "SELL":
            pnl_pct = -pnl_pct

        close_reason: str | None = None
        if trade.tp_pct is not None and pnl_pct >= trade.tp_pct:
            close_reason = "tp"
        elif trade.sl_pct is not None and pnl_pct <= trade.sl_pct:
            close_reason = "sl"

        if close_reason:
            now = datetime.now(tz=timezone.utc)
            async with get_session() as session:
                await session.execute(
                    sa_update(paper_trade_table)
                    .where(paper_trade_table.c.id == trade.id)
                    .values(
                        status="closed",
                        exit_price=price,
                        exit_time=now,
                        pnl_pct=round(pnl_pct, 2),
                        close_reason=close_reason,
                    )
                )

            symbol = trade.symbol or token[:8]
            emoji = "🎯" if close_reason == "tp" else "🛑"
            label = "TAKE-PROFIT" if close_reason == "tp" else "STOP-LOSS"
            sign = "+" if pnl_pct >= 0 else ""
            msg = (
                f"{emoji} <b>{label} hit — ${symbol}</b>\n\n"
                f"Side: {trade.side}\n"
                f"Entry: ${entry:.6g}  →  Exit: ${price:.6g}\n"
                f"P&L: <b>{sign}{pnl_pct:.2f}%</b>\n\n"
                f"Use /my-trades to see your full history."
            )
            asyncio.create_task(_send_dm(trade.telegram_user_id, msg))
            logger.info(
                "Paper trade %s hit %s — %s %.2f%% | user %s",
                trade.id[:8], label, symbol, pnl_pct, trade.telegram_user_id,
            )


async def _check_price_alerts(price_cache: dict[str, float]) -> None:
    """Check active price alerts and trigger any that crossed their target."""
    if not db.is_available():
        return

    async with get_session() as session:
        result = await session.execute(
            select(price_alert_table).where(price_alert_table.c.status == "active")
        )
        alerts = result.fetchall()

    if not alerts:
        return

    for alert in alerts:
        token = alert.token_address

        if token not in price_cache:
            price = await _get_price(token)
            if price is None:
                continue
            price_cache[token] = price
        price = price_cache[token]

        triggered = (
            (alert.direction == "above" and price >= alert.target_price) or
            (alert.direction == "below" and price <= alert.target_price)
        )

        if triggered:
            now = datetime.now(tz=timezone.utc)
            async with get_session() as session:
                await session.execute(
                    sa_update(price_alert_table)
                    .where(price_alert_table.c.id == alert.id)
                    .values(status="triggered", triggered_at=now)
                )

            symbol = alert.symbol or token[:8]
            direction_str = "above" if alert.direction == "above" else "below"
            msg = (
                f"🔔 <b>Price Alert — ${symbol}</b>\n\n"
                f"Current price: <b>${price:.6g}</b>\n"
                f"Your target: {direction_str} ${alert.target_price:.6g}\n\n"
                f"<a href='https://birdeye.so/token/{token}?chain=solana'>View on Birdeye →</a>"
            )
            asyncio.create_task(_send_dm(alert.telegram_user_id, msg))
            logger.info(
                "Price alert triggered — %s %s $%.6g | user %s",
                symbol, direction_str, alert.target_price, alert.telegram_user_id,
            )


async def run_price_monitor() -> None:
    """
    Long-running background task. Polls every 2 minutes.
    Started in the FastAPI lifespan alongside the WebSocket listener.
    """
    logger.info("Price monitor started — checking trades and alerts every %ds", POLL_INTERVAL_S)

    while True:
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            # Shared price cache per cycle — avoids redundant API calls for same token
            price_cache: dict[str, float] = {}
            await _check_paper_trades(price_cache)
            await _check_price_alerts(price_cache)
        except asyncio.CancelledError:
            logger.info("Price monitor cancelled.")
            return
        except Exception as exc:
            logger.warning("Price monitor error: %s", exc)
