"""
Telegram alert + bot commands service — Phase 4 / Phase 10.

Sends trade alerts and responds to user commands via python-telegram-bot.

Supported commands (user types in the Telegram chat):
  /start   — welcome message, confirms bot is alive
  /wallets — lists currently tracked whales with PnL and win-rate
  /help    — lists available commands
"""
from __future__ import annotations

import asyncio
import logging
import os

from telegram import Bot, Update
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot | None:
    global _bot
    if _bot is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if token:
            _bot = Bot(token=token)
    return _bot


def _chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "")


def _security_emoji(score: float | None) -> str:
    if score is None:
        return "⬜"
    if score >= 70:
        return "🟢"
    if score >= 40:
        return "🟡"
    return "🔴"


async def send_trade_alert(
    *,
    wallet_label: str,
    wallet_address: str,
    token_symbol: str,
    token_address: str,
    side: str,
    usd_value: float,
    security_score: float | None,
    smart_money: bool,
    momentum_24h: float | None,
) -> None:
    """Send a formatted trade alert to the configured Telegram chat."""
    bot = _get_bot()
    chat_id = _chat_id()

    if not bot or not chat_id:
        logger.debug("Telegram not configured — skipping alert.")
        return

    side_emoji = "🚀" if side == "BUY" else "🔻"
    momentum_str = (
        f"{momentum_24h:+.1f}%" if momentum_24h is not None else "N/A"
    )
    usd_str = f"${usd_value:,.0f}"
    solscan_url = f"https://solscan.io/account/{wallet_address}"
    token_url = f"https://birdeye.so/token/{token_address}?chain=solana"

    text = (
        f"{side_emoji} <b>Zentryx Signal</b>\n"
        f"\n"
        f"<b>{wallet_label}</b> {side} <a href='{token_url}'>${token_symbol}</a>\n"
        f"Value: <b>{usd_str}</b>\n"
        f"\n"
        f"Security: {_security_emoji(security_score)} "
        f"{'Safe' if (security_score or 0) >= 70 else 'Caution' if (security_score or 0) >= 40 else 'Risky'}"
        f" ({security_score:.0f}/100)" if security_score is not None else ""
        f"\n"
        f"Smart Money: {'✅ Yes' if smart_money else '—'}\n"
        f"Momentum: {momentum_str} (24h)\n"
        f"\n"
        f"<a href='{solscan_url}'>View wallet on Solscan</a>"
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info("Telegram alert sent for %s %s $%s", wallet_label, side, token_symbol)
    except TelegramError as exc:
        logger.warning("Telegram send failed: %s", exc)


async def send_startup_message() -> None:
    """Send a startup notification so you know the bot is alive."""
    bot = _get_bot()
    chat_id = _chat_id()
    if not bot or not chat_id:
        return
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "🟢 <b>Zentryx is online</b>\n"
                "Wallet discovery complete. Monitoring live trades on Solana."
            ),
            parse_mode="HTML",
        )
    except TelegramError as exc:
        logger.warning("Telegram startup message failed: %s", exc)


# ── Bot command handlers ────────────────────────────────────────────────────

async def _handle_start(bot: Bot, update: Update) -> None:
    chat_id = update.message.chat.id
    name = update.message.from_user.first_name or "Trader"
    text = (
        f"👋 <b>Welcome to Zentryx, {name}!</b>\n\n"
        "I track top-performing Solana whales and alert you when they make large trades.\n\n"
        "<b>Commands:</b>\n"
        "/wallets — see currently tracked whales\n"
        "/help — show this message\n\n"
        "Trade alerts will appear here automatically when whales move."
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    logger.info("Responded to /start from chat %s (%s)", chat_id, name)


async def _handle_wallets(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets  # local import to avoid circular
    chat_id = update.message.chat.id
    wallets = get_tracked_wallets()

    if not wallets:
        await bot.send_message(
            chat_id=chat_id,
            text="⏳ No wallets tracked yet. Discovery runs on startup and weekly on Sundays.",
            parse_mode="HTML",
        )
        return

    lines = ["🐋 <b>Tracked Whales</b>\n"]
    for rank, w in enumerate(wallets, start=1):
        pnl_str = f"${w.total_pnl:,.0f}" if w.total_pnl >= 0 else f"-${abs(w.total_pnl):,.0f}"
        win_pct = f"{w.win_rate * 100:.0f}%"
        lines.append(
            f"<b>#{rank} {w.label}</b>\n"
            f"  PnL: {pnl_str}  |  Win rate: {win_pct}  |  Trades: {w.trade_count:,}\n"
            f"  <code>{w.address[:20]}...</code>"
        )

    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Responded to /wallets from chat %s — sent %d wallets", chat_id, len(wallets))


async def _handle_help(bot: Bot, update: Update) -> None:
    chat_id = update.message.chat.id
    text = (
        "📋 <b>Zentryx Commands</b>\n\n"
        "/start — welcome + overview\n"
        "/wallets — list tracked whale wallets with PnL and win rate\n"
        "/help — show this message\n\n"
        "Trade alerts are sent automatically when a tracked whale makes a $5,000+ trade."
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def _dispatch(bot: Bot, update: Update) -> None:
    """Route an incoming Update to the correct command handler."""
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.strip().lower()
    if text.startswith("/start"):
        await _handle_start(bot, update)
    elif text.startswith("/wallets"):
        await _handle_wallets(bot, update)
    elif text.startswith("/help"):
        await _handle_help(bot, update)
    else:
        # Unknown command — silently ignore
        pass


async def run_bot_command_loop() -> None:
    """
    Long-running coroutine that polls Telegram for new messages (getUpdates).
    Runs as a background task in the FastAPI lifespan alongside the polling worker.
    Uses offset-based polling — no webhooks needed, works on localhost.
    """
    bot = _get_bot()
    if not bot:
        logger.warning("Telegram bot token not set — command loop disabled.")
        return

    logger.info("Telegram command loop started — listening for /start, /wallets, /help")
    offset: int | None = None

    while True:
        try:
            updates = await bot.get_updates(
                offset=offset,
                timeout=20,          # long-poll: waits up to 20s for new messages
                allowed_updates=["message"],
            )
            for update in updates:
                offset = update.update_id + 1
                try:
                    await _dispatch(bot, update)
                except Exception as exc:
                    logger.warning("Command dispatch error: %s", exc)
        except asyncio.CancelledError:
            logger.info("Telegram command loop cancelled.")
            return
        except TelegramError as exc:
            logger.warning("Telegram getUpdates error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
        except Exception as exc:
            logger.warning("Unexpected error in command loop: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
