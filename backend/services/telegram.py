"""
Telegram alert + bot commands service — Phase 4 / Phase 10.

Sends trade alerts and responds to user commands via python-telegram-bot.

Supported commands (user types in the Telegram chat):
  /start            — welcome message, confirms bot is alive
  /wallets          — list all tracked whales with PnL and win rate
  /stats            — aggregate metrics across all tracked wallets
  /top [n]          — show top N wallets by PnL (default 5)
  /wallet [address] — look up a specific wallet by address (partial match ok)
  /filter [n%]      — filter whales with at least N% win rate
  /watch [address]  — add a wallet to your personal watchlist
  /unwatch [addr]   — remove a wallet from your watchlist
  /my-wallets       — show your personal watchlist
  /help             — list all available commands
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from telegram import Bot, Update
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

_bot: Bot | None = None

# Per-chat command cooldown: {chat_id: last_command_timestamp}
_last_command: dict[int, float] = {}
_COOLDOWN_SECONDS = 5.0


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

    sec_str = (
        f"{_security_emoji(security_score)} "
        f"{'Safe' if (security_score or 0) >= 70 else 'Caution' if (security_score or 0) >= 40 else 'Risky'}"
        + (f" ({security_score:.0f}/100)" if security_score is not None else "")
    )
    text = (
        f"{side_emoji} <b>Zentryx Signal</b>\n"
        f"\n"
        f"<b>{wallet_label}</b> {side} <a href='{token_url}'>${token_symbol}</a>\n"
        f"Value: <b>{usd_str}</b>\n"
        f"\n"
        f"Security: {sec_str}\n"
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


async def send_personal_trade_alert(
    *,
    telegram_user_id: int,
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
    """Send a trade alert DM to a specific Telegram user (watchlist notification)."""
    bot = _get_bot()
    if not bot:
        return

    side_emoji = "🚀" if side == "BUY" else "🔻"
    momentum_str = f"{momentum_24h:+.1f}%" if momentum_24h is not None else "N/A"
    usd_str = f"${usd_value:,.0f}"
    token_url = f"https://birdeye.so/token/{token_address}?chain=solana"
    solscan_url = f"https://solscan.io/account/{wallet_address}"

    sec_str = (
        f"{_security_emoji(security_score)} {security_score:.0f}/100"
        if security_score is not None
        else "⬜ N/A"
    )

    text = (
        f"{side_emoji} <b>Watchlist Alert</b>\n"
        f"\n"
        f"<b>{wallet_label}</b> {side} <a href='{token_url}'>${token_symbol}</a>\n"
        f"Value: <b>{usd_str}</b>\n"
        f"\n"
        f"Security: {sec_str}\n"
        f"Smart Money: {'✅ Yes' if smart_money else '—'}\n"
        f"Momentum: {momentum_str} (24h)\n"
        f"\n"
        f"<a href='{solscan_url}'>View wallet on Solscan</a>"
    )

    try:
        await bot.send_message(
            chat_id=telegram_user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        logger.debug("Personal alert to user %s failed: %s", telegram_user_id, exc)


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

async def _check_cooldown(bot: Bot, update: Update) -> bool:
    """
    Returns True if the command is allowed. Returns False (and notifies user)
    if the chat is within the 5-second cooldown window.
    """
    chat_id = update.message.chat.id
    now = time.monotonic()
    last = _last_command.get(chat_id, 0.0)
    remaining = _COOLDOWN_SECONDS - (now - last)
    if remaining > 0:
        await bot.send_message(
            chat_id=chat_id,
            text=f"⏱ Slow down! Try again in <b>{remaining:.1f}s</b>.",
            parse_mode="HTML",
        )
        return False
    _last_command[chat_id] = now
    return True


async def _handle_start(bot: Bot, update: Update) -> None:
    chat_id = update.message.chat.id
    name = update.message.from_user.first_name or "Trader"
    text = (
        f"👋 <b>Welcome to Zentryx, {name}!</b>\n\n"
        "I track top-performing Solana whales and alert you when they make large trades.\n\n"
        "<b>Available commands:</b>\n"
        "/wallets — list all tracked whales\n"
        "/stats — aggregate metrics across all wallets\n"
        "/top [n] — top N wallets by PnL (e.g. /top 10)\n"
        "/wallet [address] — look up a specific wallet\n"
        "/filter [n%] — filter by min win rate (e.g. /filter 70)\n"
        "/watch [address] — add a whale to your personal watchlist\n"
        "/unwatch [address] — remove from your watchlist\n"
        "/my-wallets — view your personal watchlist\n"
        "/help — show this message\n\n"
        "Trade alerts appear here automatically when whales move $2,000+.\n"
        "Watchlist alerts are sent directly to you as DMs."
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    logger.info("Responded to /start from chat %s (%s)", chat_id, name)


async def _handle_wallets(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets
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


async def _handle_stats(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets
    chat_id = update.message.chat.id
    wallets = get_tracked_wallets()

    if not wallets:
        await bot.send_message(
            chat_id=chat_id,
            text="⏳ No wallets tracked yet. Discovery runs on startup and weekly on Sundays.",
            parse_mode="HTML",
        )
        return

    total_pnl = sum(w.total_pnl for w in wallets)
    avg_win_rate = sum(w.win_rate for w in wallets) / len(wallets)
    best = max(wallets, key=lambda w: w.total_pnl)
    top_win = max(wallets, key=lambda w: w.win_rate)

    pnl_str = f"${total_pnl:,.0f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.0f}"
    best_pnl_str = f"${best.total_pnl:,.0f}" if best.total_pnl >= 0 else f"-${abs(best.total_pnl):,.0f}"

    text = (
        "📊 <b>Zentryx Dashboard Stats</b>\n\n"
        f"🐋 Wallets tracked: <b>{len(wallets)}</b>\n"
        f"💰 Total PnL (7D): <b>{pnl_str}</b>\n"
        f"📈 Avg win rate: <b>{avg_win_rate * 100:.1f}%</b>\n"
        f"🏆 Best performer: <b>{best.label}</b> ({best_pnl_str})\n"
        f"⭐ Highest win rate: <b>{top_win.label}</b> ({top_win.win_rate * 100:.0f}%)\n\n"
        "Use /wallets for full list or /top for ranked view."
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    logger.info("Responded to /stats from chat %s", chat_id)


async def _handle_top(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets
    chat_id = update.message.chat.id
    parts = (update.message.text or "").strip().split()

    n = 5  # default
    if len(parts) >= 2 and parts[1].isdigit():
        n = max(1, min(int(parts[1]), 15))  # clamp 1–15

    wallets = sorted(get_tracked_wallets(), key=lambda w: w.total_pnl, reverse=True)[:n]

    if not wallets:
        await bot.send_message(
            chat_id=chat_id,
            text="⏳ No wallets tracked yet.",
            parse_mode="HTML",
        )
        return

    lines = [f"🏆 <b>Top {len(wallets)} Whales by PnL</b>\n"]
    for rank, w in enumerate(wallets, start=1):
        pnl_str = f"${w.total_pnl:,.0f}" if w.total_pnl >= 0 else f"-${abs(w.total_pnl):,.0f}"
        lines.append(
            f"#{rank} <b>{w.label}</b> — {pnl_str} | {w.win_rate * 100:.0f}% win | {w.trade_count} trades"
        )

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Responded to /top %d from chat %s", n, chat_id)


async def _handle_wallet_lookup(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets
    chat_id = update.message.chat.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Usage: <code>/wallet [address]</code>\nExample: <code>/wallet Hm9qLg5w</code>",
            parse_mode="HTML",
        )
        return

    query = parts[1].lower()
    wallets = get_tracked_wallets()
    found = next(
        (w for w in wallets if w.address.lower().startswith(query) or w.address.lower() == query),
        None,
    )

    if not found:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ No tracked wallet found matching <code>{query}</code>.\n\nUse /wallets to see all tracked addresses.",
            parse_mode="HTML",
        )
        return

    pnl_str = f"${found.total_pnl:,.0f}" if found.total_pnl >= 0 else f"-${abs(found.total_pnl):,.0f}"
    solscan_url = f"https://solscan.io/account/{found.address}"
    text = (
        f"🐋 <b>{found.label}</b>\n\n"
        f"💰 PnL (7D): <b>{pnl_str}</b>\n"
        f"📈 Win rate: <b>{found.win_rate * 100:.1f}%</b>\n"
        f"🔄 Trades: <b>{found.trade_count:,}</b>\n"
        f"📍 Address: <code>{found.address}</code>\n\n"
        f"<a href='{solscan_url}'>View on Solscan →</a>"
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    logger.info("Responded to /wallet lookup for %s from chat %s", found.address[:8], chat_id)


async def _handle_filter(bot: Bot, update: Update) -> None:
    from services.wallet_discovery import get_tracked_wallets
    chat_id = update.message.chat.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Usage: <code>/filter [win_rate%]</code>\nExample: <code>/filter 70</code> shows wallets with 70%+ win rate.",
            parse_mode="HTML",
        )
        return

    try:
        threshold_pct = float(parts[1])
        if not (0 <= threshold_pct <= 100):
            raise ValueError
    except ValueError:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Invalid win rate. Use a number between 0 and 100.\nExample: <code>/filter 65</code>",
            parse_mode="HTML",
        )
        return

    threshold = threshold_pct / 100.0
    filtered = sorted(
        [w for w in get_tracked_wallets() if w.win_rate >= threshold],
        key=lambda w: w.total_pnl,
        reverse=True,
    )

    if not filtered:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔍 No wallets found with ≥{threshold_pct:.0f}% win rate.\n\nTry a lower threshold or use /wallets to see all.",
            parse_mode="HTML",
        )
        return

    lines = [f"🔍 <b>Wallets with ≥{threshold_pct:.0f}% win rate ({len(filtered)} found)</b>\n"]
    for rank, w in enumerate(filtered, start=1):
        pnl_str = f"${w.total_pnl:,.0f}" if w.total_pnl >= 0 else f"-${abs(w.total_pnl):,.0f}"
        lines.append(
            f"#{rank} <b>{w.label}</b> — {w.win_rate * 100:.0f}% win | {pnl_str} | {w.trade_count} trades"
        )

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Responded to /filter %.0f%% from chat %s — %d results", threshold_pct, chat_id, len(filtered))


async def _handle_help(bot: Bot, update: Update) -> None:
    chat_id = update.message.chat.id
    text = (
        "📋 <b>Zentryx Commands</b>\n\n"
        "/start — welcome message and overview\n"
        "/wallets — list all tracked whale wallets\n"
        "/stats — aggregate metrics (total PnL, avg win rate, best performer)\n"
        "/top [n] — top N wallets by PnL, default 5 (e.g. /top 10)\n"
        "/wallet [address] — look up a specific wallet (partial address ok)\n"
        "/filter [n%] — filter wallets by min win rate (e.g. /filter 70)\n"
        "/watch [address] — add a whale to your personal watchlist\n"
        "/unwatch [address] — remove a whale from your watchlist\n"
        "/my-wallets — view your personal watchlist\n"
        "/help — show this message\n\n"
        "🔔 Trade alerts are sent automatically when a tracked whale makes a $2,000+ trade.\n"
        "📩 Watchlist alerts are DM'd directly to you for wallets you /watch."
    )
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def _handle_watch(bot: Bot, update: Update) -> None:
    """Handle /watch <address> — add a tracked wallet to the user's personal watchlist."""
    import db
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/watch [address]</code>\n"
                "Example: <code>/watch Hm9qLg5w</code>\n\n"
                "Use /wallets to see all tracked whale addresses."
            ),
            parse_mode="HTML",
        )
        return

    query = parts[1].lower()
    from services.wallet_discovery import get_tracked_wallets
    wallets = get_tracked_wallets()
    found = next(
        (w for w in wallets if w.address.lower().startswith(query) or w.address.lower() == query),
        None,
    )

    if not found:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ No tracked wallet found matching <code>{query}</code>.\n\n"
                "Use /wallets to see all tracked addresses."
            ),
            parse_mode="HTML",
        )
        return

    if not db.is_available():
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Watchlist unavailable — database not connected.",
            parse_mode="HTML",
        )
        return

    db_wallet = await db.prisma.wallet.find_unique(where={"address": found.address})
    if not db_wallet:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Wallet not found in database yet. Try again after next discovery.",
            parse_mode="HTML",
        )
        return

    try:
        await db.prisma.userwatchlist.create(
            data={"telegramUserId": telegram_user_id, "walletId": db_wallet.id}
        )
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ <b>{found.label}</b> added to your watchlist!\n\n"
                f"You'll receive a personal DM whenever this whale makes a $2,000+ trade.\n"
                f"Use /my-wallets to see your full watchlist."
            ),
            parse_mode="HTML",
        )
        logger.info("User %s added %s to watchlist.", telegram_user_id, found.label)
    except Exception:
        # Unique constraint violation = already watching
        await bot.send_message(
            chat_id=chat_id,
            text=f"ℹ️ You're already watching <b>{found.label}</b>.",
            parse_mode="HTML",
        )


async def _handle_unwatch(bot: Bot, update: Update) -> None:
    """Handle /unwatch <address> — remove a wallet from the user's watchlist."""
    import db
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Usage: <code>/unwatch [address]</code>",
            parse_mode="HTML",
        )
        return

    if not db.is_available():
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Watchlist unavailable — database not connected.",
            parse_mode="HTML",
        )
        return

    query = parts[1].lower()
    db_wallet = await db.prisma.wallet.find_first(
        where={"address": {"startswith": query}}
    )
    if not db_wallet:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ No wallet found matching <code>{query}</code>.",
            parse_mode="HTML",
        )
        return

    deleted = await db.prisma.userwatchlist.delete_many(
        where={"telegramUserId": telegram_user_id, "walletId": db_wallet.id}
    )

    if deleted:
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ <b>{db_wallet.label}</b> removed from your watchlist.",
            parse_mode="HTML",
        )
        logger.info("User %s removed %s from watchlist.", telegram_user_id, db_wallet.label)
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"ℹ️ <b>{db_wallet.label}</b> wasn't in your watchlist.",
            parse_mode="HTML",
        )


async def _handle_my_wallets(bot: Bot, update: Update) -> None:
    """Handle /my-wallets — display the user's personal watchlist."""
    import db
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id

    if not db.is_available():
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Watchlist unavailable — database not connected.",
            parse_mode="HTML",
        )
        return

    items = await db.prisma.userwatchlist.find_many(
        where={"telegramUserId": telegram_user_id},
        include={"wallet": True},
        order={"addedAt": "asc"},
    )

    if not items:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "📋 Your watchlist is empty.\n\n"
                "Use <code>/watch [address]</code> to add a whale.\n"
                "Try /wallets to see all tracked addresses."
            ),
            parse_mode="HTML",
        )
        return

    lines = [f"📋 <b>Your Watchlist ({len(items)} wallet{'s' if len(items) != 1 else ''})</b>\n"]
    for i, item in enumerate(items, start=1):
        w = item.wallet
        pnl_str = f"${w.totalPnl:,.0f}" if w.totalPnl >= 0 else f"-${abs(w.totalPnl):,.0f}"
        lines.append(
            f"#{i} <b>{w.label}</b> — {pnl_str} | {w.winRate * 100:.0f}% win\n"
            f"<code>{w.address[:20]}...</code>"
        )
    lines.append("\nUse <code>/unwatch [address]</code> to remove a wallet.")

    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Responded to /my-wallets from user %s — %d items.", telegram_user_id, len(items))


async def _handle_test_alert(bot: Bot, update: Update) -> None:
    """Handle /test_alert — send a mock trade alert to verify formatting."""
    chat_id = update.message.chat.id
    await bot.send_message(
        chat_id=chat_id,
        text="🔄 Sending test alert to channel...",
        parse_mode="HTML",
    )
    await send_trade_alert(
        wallet_label="Whale #1 (Test)",
        wallet_address="So11111111111111111111111111111111111111112",
        token_symbol="SOL",
        token_address="So11111111111111111111111111111111111111112",
        side="BUY",
        usd_value=5500.0,
        security_score=72.0,
        smart_money=True,
        momentum_24h=8.5,
    )
    logger.info("Test alert triggered by chat %s", chat_id)


async def _dispatch(bot: Bot, update: Update) -> None:
    """Route an incoming Update to the correct command handler."""
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip().lower()

    # /start and /help skip cooldown so users can always access help
    if text.startswith("/start"):
        await _handle_start(bot, update)
        return
    if text.startswith("/help"):
        await _handle_help(bot, update)
        return

    # All other commands are rate-limited
    if not await _check_cooldown(bot, update):
        return

    if text.startswith("/wallets"):
        await _handle_wallets(bot, update)
    elif text.startswith("/stats"):
        await _handle_stats(bot, update)
    elif text.startswith("/top"):
        await _handle_top(bot, update)
    elif text.startswith("/wallet ") or text == "/wallet":
        await _handle_wallet_lookup(bot, update)
    elif text.startswith("/filter"):
        await _handle_filter(bot, update)
    elif text.startswith("/watch ") or text == "/watch":
        await _handle_watch(bot, update)
    elif text.startswith("/unwatch ") or text == "/unwatch":
        await _handle_unwatch(bot, update)
    elif text.startswith("/my-wallets") or text == "/my-wallets":
        await _handle_my_wallets(bot, update)
    elif text.startswith("/test_alert") or text == "/test_alert":
        await _handle_test_alert(bot, update)
    # Unknown commands silently ignored


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

    logger.info("Telegram command loop started — listening for /start, /wallets, /stats, /top, /wallet, /filter, /watch, /unwatch, /my-wallets, /help")
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
