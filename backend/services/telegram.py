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
import html
import logging
import os
import time

from telegram import Bot, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeDefault, Update
from telegram.error import TelegramError
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    """Personal user chat ID — used for bot command replies and watchlist DMs."""
    return os.getenv("TELEGRAM_CHAT_ID", "")


def _group_chat_id() -> str:
    """Shared group/channel ID — used for public signal alerts and daily briefing.
    Falls back to TELEGRAM_CHAT_ID if TELEGRAM_GROUP_CHAT_ID is not set.
    """
    return os.getenv("TELEGRAM_GROUP_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")


async def _db_find_wallet_by_address(address: str):
    """Return a wallet row by exact address, or None."""
    from db import wallet_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(wallet_table).where(wallet_table.c.address == address)
        )
        return result.fetchone()


async def _db_find_wallet_by_address_prefix(prefix: str):
    """Return a wallet row whose address starts with prefix (case-insensitive), or None."""
    from sqlalchemy import func
    from db import wallet_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(wallet_table).where(
                func.lower(wallet_table.c.address).like(prefix.lower() + "%")
            )
        )
        return result.fetchone()


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
    copy_score: float | None = None,
    consensus_count: int = 0,
) -> None:
    """Send a formatted trade alert to the group/channel."""
    bot = _get_bot()
    chat_id = _group_chat_id()

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

    # Consensus badge (prepended if 2+ whales bought same token in 2h window)
    if consensus_count >= 4:
        consensus_str = "🔥 <b>EXTREME CONSENSUS</b> (4+ whales)\n"
    elif consensus_count == 3:
        consensus_str = "⚡ <b>HIGH CONSENSUS</b> (3 whales)\n"
    elif consensus_count == 2:
        consensus_str = "💡 <b>MODERATE CONSENSUS</b> (2 whales)\n"
    else:
        consensus_str = ""

    # Copy score badge
    if copy_score is not None:
        cs_emoji = "🟢" if copy_score >= 70 else ("🟡" if copy_score >= 50 else "🔴")
        cs_str = f"\n{cs_emoji} Copy Score: <b>{copy_score:.0f}/100</b>"
    else:
        cs_str = ""

    text = (
        f"{side_emoji} <b>Zentryx Signal</b>\n"
        f"\n"
        f"{consensus_str}"
        f"<b>{wallet_label}</b> {side} <a href='{token_url}'>${token_symbol}</a>\n"
        f"Value: <b>{usd_str}</b>\n"
        f"\n"
        f"Security: {sec_str}\n"
        f"Smart Money: {'✅ Yes' if smart_money else '—'}\n"
        f"Momentum: {momentum_str} (24h)"
        f"{cs_str}\n"
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
    copy_score: float | None = None,
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
    if copy_score is not None:
        cs_emoji = "🟢" if copy_score >= 70 else ("🟡" if copy_score >= 50 else "🔴")
        cs_str = f"\n{cs_emoji} Copy Score: <b>{copy_score:.0f}/100</b>"
    else:
        cs_str = ""

    text = (
        f"{side_emoji} <b>Watchlist Alert</b>\n"
        f"\n"
        f"<b>{wallet_label}</b> {side} <a href='{token_url}'>${token_symbol}</a>\n"
        f"Value: <b>{usd_str}</b>\n"
        f"\n"
        f"Security: {sec_str}\n"
        f"Smart Money: {'✅ Yes' if smart_money else '—'}\n"
        f"Momentum: {momentum_str} (24h)"
        f"{cs_str}\n"
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


async def send_trade_alert_ai_followup(
    *,
    token_symbol: str,
    token_address: str,
    recommendation: str,
    analysis: str,
    telegram_user_id: int | None = None,
) -> None:
    """Send a follow-up AI verdict message to the personal bot after the initial alert."""
    bot = _get_bot()
    chat_id = str(telegram_user_id) if telegram_user_id is not None else _chat_id()
    if not bot or not chat_id:
        return

    rec_emoji = {
        "STRONG_BUY": "🟢",
        "BUY": "🟩",
        "HOLD": "🟡",
        "SELL": "🟠",
        "AVOID": "🔴",
    }.get(recommendation, "⬜")
    rec_label = recommendation.replace("_", " ")
    token_url = f"https://birdeye.so/token/{token_address}?chain=solana"

    text = (
        f"🤖 <b>AI Verdict — <a href='{token_url}'>${token_symbol}</a></b>\n"
        f"{rec_emoji} <b>{rec_label}</b>\n\n"
        f"{analysis}"
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info("AI followup sent for $%s: %s", token_symbol, recommendation)
    except TelegramError as exc:
        logger.debug("AI followup send failed: %s", exc)


async def send_startup_message() -> None:
    """Send a startup notification to the group so you know the bot is alive."""
    bot = _get_bot()
    chat_id = _group_chat_id()
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


async def _build_briefing_data() -> dict:
    """
    Aggregate the last 24 hours of whale trading activity from DB.

    Returns a dict with keys:
      total_trades, buy_count, sell_count, total_volume_usd,
      accumulation_tokens (list of {symbol, wallet_count, total_usd}),
      exit_tokens         (list of {symbol, wallet_count, total_usd}),
      best_signal         ({symbol, return_pct}) or None
    """
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from db import trade_event_table, get_session
    from services.signal_stats import get_cached_stats

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)

    async with get_session() as session:
        result = await session.execute(
            select(trade_event_table).where(
                trade_event_table.c.timestamp >= cutoff
            )
        )
        rows = result.fetchall()

    total_trades = len(rows)
    buy_rows = [r for r in rows if (r.side or "").upper() == "BUY"]
    sell_rows = [r for r in rows if (r.side or "").upper() == "SELL"]
    buy_count = len(buy_rows)
    sell_count = len(sell_rows)
    total_volume_usd = sum(r.usd_value or 0.0 for r in rows)

    # Group BUY rows by (token_address, symbol) → count unique wallets + total usd
    def _group_by_token(trade_rows: list) -> list[dict]:
        token_map: dict[str, dict] = {}
        for r in trade_rows:
            key = r.token_address
            sym = r.token_symbol or key[:8]
            if key not in token_map:
                token_map[key] = {"symbol": sym, "wallets": set(), "total_usd": 0.0}
            if r.wallet_id:
                token_map[key]["wallets"].add(r.wallet_id)
            token_map[key]["total_usd"] += r.usd_value or 0.0

        grouped = [
            {"symbol": v["symbol"], "wallet_count": len(v["wallets"]), "total_usd": v["total_usd"]}
            for v in token_map.values()
        ]
        return sorted(grouped, key=lambda x: x["wallet_count"], reverse=True)[:3]

    accumulation_tokens = _group_by_token(buy_rows)
    exit_tokens = _group_by_token(sell_rows)

    # Best signal from signal_stats cache
    best_signal = None
    stats = get_cached_stats()
    if stats and stats.get("top_performers"):
        top = stats["top_performers"][0]
        best_signal = {"symbol": top.get("symbol", "???"), "return_pct": top.get("return_pct", 0.0)}

    return {
        "total_trades": total_trades,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_volume_usd": total_volume_usd,
        "accumulation_tokens": accumulation_tokens,
        "exit_tokens": exit_tokens,
        "best_signal": best_signal,
    }


async def send_daily_briefing() -> None:
    """
    Build and send the daily Zentryx market briefing to the Telegram channel.
    Called by the scheduler every day at 09:00 UTC.
    AI section is included if Groq is available; omitted gracefully if not.
    """
    bot = _get_bot()
    chat_id = _group_chat_id()
    if not bot or not chat_id:
        logger.debug("Telegram not configured — skipping daily briefing.")
        return

    try:
        from datetime import datetime, timezone
        from services.gemini import analyse_daily_briefing

        data = await _build_briefing_data()

        if data["total_trades"] == 0:
            await bot.send_message(
                chat_id=chat_id,
                text="🌅 <b>Zentryx Daily Briefing</b>\nNo whale trades recorded in the last 24 hours. Quiet market day.",
                parse_mode="HTML",
            )
            return

        ai_insight = await analyse_daily_briefing(data)

        # Header
        now_utc = datetime.now(tz=timezone.utc)
        # Cross-platform day formatting (no leading zero)
        day_num = now_utc.day
        month_name = now_utc.strftime("%B")
        weekday = now_utc.strftime("%A")
        date_str = f"{weekday} {day_num} {month_name}"

        lines: list[str] = [
            f"🌅 <b>ZENTRYX DAILY BRIEFING — {date_str}</b>",
            "━━━━━━━━━━━━━━━━━━",
            "",
            "📊 <b>Last 24 Hours</b>",
            f"• {data['total_trades']} whale trades tracked",
            f"• {data['buy_count']} BUY signals / {data['sell_count']} SELL signals",
            f"• ${data['total_volume_usd']:,.0f} total notional volume",
        ]

        # Accumulation block
        if data["accumulation_tokens"]:
            lines += ["", "🔥 <b>Smart Money Accumulation</b>"]
            for i, t in enumerate(data["accumulation_tokens"], 1):
                lines.append(
                    f"{i}. ${t['symbol']} — {t['wallet_count']} wallet(s) entered (${t['total_usd']:,.0f} combined)"
                )

        # Exit block — only if there are sell events
        if data["exit_tokens"] and data["sell_count"] > 0:
            lines += ["", "⚠️ <b>Smart Money Exits</b>"]
            for t in data["exit_tokens"]:
                lines.append(f"• ${t['symbol']} — {t['wallet_count']} wallet(s) reduced positions")

        # AI insight — omitted if Groq unavailable
        if ai_insight:
            lines += ["", "🤖 <b>AI Market Insight</b>", ai_insight]

        # Best signal — omitted if no profitability data yet
        if data["best_signal"]:
            s = data["best_signal"]
            ret = s["return_pct"]
            ret_str = f"{ret:+.1f}%"
            badge = "✅" if ret > 0 else "❌"
            lines += ["", f"📈 <b>Best Signal Yesterday</b>", f"${s['symbol']} {ret_str} since whale entry {badge}"]

        # Footer
        lines += ["", "View live → zentryx.app/live"]

        text = "\n".join(lines)
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        logger.info("Daily briefing sent: %d trades, AI=%s", data["total_trades"], ai_insight is not None)

    except Exception as exc:
        logger.error("Daily briefing failed: %s", exc, exc_info=True)


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
        "/signal [token] — copy score + factor breakdown (fast)\n"
        "/analyze [token] — AI deep-dive analysis via Groq\n"
        "/track [token] [tp%] [sl%] — open a paper trade\n"
        "/my-trades — view your paper trade positions\n"
        "/trending — top 5 trending Solana tokens\n"
        "/newlisting — 5 newest token launches\n"
        "/help — show this message\n\n"
        "🔔 Trade alerts fire automatically when whales move $1,000+.\n"
        "📩 Watchlist alerts are DM'd directly to you."
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

    from services.signal_stats import get_cached_stats
    stats = get_cached_stats()
    if stats and stats.get("total_signals", 0) > 0:
        text += (
            f"\n\n📈 <b>Signal Accuracy</b>\n"
            f"{stats['win_rate']:.1f}% of smart money BUYs profitable\n"
            f"Avg return: {stats['avg_return_pct']:+.1f}% ({stats['total_signals']} signals)"
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
        "/track [token] [tp%] [sl%] — open a paper trade at current price\n"
        "/my-trades — view your open and recent paper trades\n"
        "/alert [token] [price] [above|below] — set a price alert\n"
        "/my-alerts — view your active price alerts\n"
        "/cancel-alert [id] — cancel a price alert\n"
        "/signal [token] — copy score + per-factor breakdown (fast, no AI)\n"
        "/analyze [token] — full AI narrative analysis via Groq (~20s)\n"
        "/close-trade [id] — manually close an open paper trade\n"
        "/trending — top 5 trending tokens on Solana right now\n"
        "/newlisting — 5 newest token launches (menu command)\n"
        "Alias: /new-listings also works\n"
        "/help — show this message\n\n"
        "🔔 Trade alerts fire automatically when whales move $1,000+.\n"
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

    import db
    from db import wallet_table, user_watchlist_table, get_session

    db_wallet = await _db_find_wallet_by_address(found.address)
    if not db_wallet:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Wallet not found in database yet. Try again after next discovery.",
            parse_mode="HTML",
        )
        return

    try:
        import uuid
        from datetime import datetime, timezone
        stmt = pg_insert(user_watchlist_table).values(
            id=str(uuid.uuid4()),
            telegram_user_id=telegram_user_id,
            wallet_id=db_wallet.id,
            added_at=datetime.now(tz=timezone.utc),
        ).on_conflict_do_nothing()
        async with get_session() as session:
            await session.execute(stmt)
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
    db_wallet = await _db_find_wallet_by_address_prefix(query)
    if not db_wallet:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ No wallet found matching <code>{query}</code>.",
            parse_mode="HTML",
        )
        return

    from db import wallet_table, user_watchlist_table, get_session
    async with get_session() as session:
        result = await session.execute(
            delete(user_watchlist_table).where(
                user_watchlist_table.c.telegram_user_id == telegram_user_id,
                user_watchlist_table.c.wallet_id == db_wallet.id,
            )
        )
        deleted = result.rowcount

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

    from db import wallet_table, user_watchlist_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(user_watchlist_table, wallet_table)
            .join(wallet_table, user_watchlist_table.c.wallet_id == wallet_table.c.id)
            .where(user_watchlist_table.c.telegram_user_id == telegram_user_id)
            .order_by(user_watchlist_table.c.added_at.asc())
        )
        rows = result.fetchall()

    if not rows:
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

    lines = [f"📋 <b>Your Watchlist ({len(rows)} wallet{'s' if len(rows) != 1 else ''})</b>\n"]
    for i, row in enumerate(rows, start=1):
        pnl = row.total_pnl or 0.0
        pnl_str = f"${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        lines.append(
            f"#{i} <b>{row.label}</b> — {pnl_str} | {(row.win_rate or 0) * 100:.0f}% win\n"
            f"<code>{row.address[:20]}...</code>"
        )
    lines.append("\nUse <code>/unwatch [address]</code> to remove a wallet.")

    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="HTML",
    )
    logger.info("Responded to /my-wallets from user %s — %d items.", telegram_user_id, len(rows))


async def _handle_track(bot: Bot, update: Update) -> None:
    """/track <token_address> [tp%] [sl%] — open a paper trade at current price."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/track [token_address] [tp%] [sl%]</code>\n"
                "Example: <code>/track DezXAZ8z7Pnr 40 -15</code>\n"
                "Opens a virtual BUY at current price with 40% TP and 15% SL."
            ),
            parse_mode="HTML",
        )
        return

    token_address = parts[1]
    tp_pct = float(parts[2]) if len(parts) >= 3 else None
    sl_pct = float(parts[3]) if len(parts) >= 4 else None

    # Fetch price
    try:
        from services import birdeye
        raw = await birdeye.get_token_price(token_address)
        entry_price = float((raw.get("data") or {}).get("value") or 0)
        symbol = token_address[:8]
        # Try to get symbol from overview
        try:
            ov = await birdeye.get_token_overview(token_address)
            sym = (ov.get("data") or {}).get("symbol")
            if sym:
                symbol = sym
        except Exception:
            pass
    except Exception as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ Failed to fetch price: {exc}", parse_mode="HTML")
        return

    if not entry_price:
        await bot.send_message(chat_id=chat_id, text="❌ Could not resolve token price. Check the address.", parse_mode="HTML")
        return

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    import uuid
    from datetime import datetime, timezone
    from db import paper_trade_table, get_session
    trade_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    async with get_session() as session:
        await session.execute(
            paper_trade_table.insert().values(
                id=trade_id,
                telegram_user_id=telegram_user_id,
                token_address=token_address,
                symbol=symbol,
                side="BUY",
                entry_price=entry_price,
                entry_time=now,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                position_size_usd=None,
                status="open",
                exit_price=None,
                exit_time=None,
                pnl_pct=None,
                close_reason=None,
                created_at=now,
            )
        )

    tp_str = f"+{tp_pct}%" if tp_pct is not None else "None"
    sl_str = f"{sl_pct}%" if sl_pct is not None else "None"
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ <b>Paper trade opened</b>\n\n"
            f"Token: <b>${symbol}</b>\n"
            f"Entry: <b>${entry_price:.6g}</b>\n"
            f"Take-profit: {tp_str}  |  Stop-loss: {sl_str}\n\n"
            f"I'll DM you when the target is hit.\n"
            f"Use /my-trades to see all open positions."
        ),
        parse_mode="HTML",
    )
    logger.info("User %s opened paper trade on %s at $%s", telegram_user_id, symbol, entry_price)


async def _handle_my_trades(bot: Bot, update: Update) -> None:
    """/my-trades — list all open and recently closed paper trades."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    from sqlalchemy import select
    from db import paper_trade_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(paper_trade_table)
            .where(paper_trade_table.c.telegram_user_id == telegram_user_id)
            .order_by(paper_trade_table.c.created_at.desc())
            .limit(10)
        )
        trades = result.fetchall()

    if not trades:
        await bot.send_message(
            chat_id=chat_id,
            text="📊 No paper trades yet. Use <code>/track [token]</code> to start one.",
            parse_mode="HTML",
        )
        return

    lines = ["<b>Your Paper Trades</b>\n"]
    for t in trades:
        status_emoji = "🟢" if t.status == "open" else ("🎯" if t.close_reason == "tp" else ("🛑" if t.close_reason == "sl" else "⚪"))
        pnl_str = ""
        if t.pnl_pct is not None:
            sign = "+" if t.pnl_pct >= 0 else ""
            pnl_str = f" | <b>{sign}{t.pnl_pct:.2f}%</b>"
        lines.append(
            f"{status_emoji} <b>${t.symbol}</b> @${t.entry_price:.6g}{pnl_str} [{t.status}]"
        )

    lines.append("\nUse /track to open a new position.")
    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")


async def _handle_alert(bot: Bot, update: Update) -> None:
    """/alert <token_address> <price> [above|below] — set a price alert."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 3:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/alert [token_address] [price] [above|below]</code>\n"
                "Example: <code>/alert DezXAZ8z7Pnr 0.000045 above</code>\n"
                "Defaults to 'above' if direction not specified."
            ),
            parse_mode="HTML",
        )
        return

    token_address = parts[1]
    try:
        target_price = float(parts[2])
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="❌ Invalid price. Use a number like 0.000045", parse_mode="HTML")
        return

    direction = parts[3].lower() if len(parts) >= 4 else "above"
    if direction not in ("above", "below"):
        direction = "above"

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    import uuid
    from datetime import datetime, timezone
    from db import price_alert_table, get_session
    from services import birdeye

    symbol = token_address[:8]
    try:
        ov = await birdeye.get_token_overview(token_address)
        sym = (ov.get("data") or {}).get("symbol")
        if sym:
            symbol = sym
    except Exception:
        pass

    alert_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    async with get_session() as session:
        await session.execute(
            price_alert_table.insert().values(
                id=alert_id,
                telegram_user_id=telegram_user_id,
                token_address=token_address,
                symbol=symbol,
                target_price=target_price,
                direction=direction,
                created_at=now,
                triggered_at=None,
                status="active",
            )
        )

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🔔 <b>Price alert set</b>\n\n"
            f"Token: <b>${symbol}</b>\n"
            f"Alert when price goes <b>{direction}</b> ${target_price:.6g}\n\n"
            f"I'll DM you when triggered.\n"
            f"Use /my-alerts to manage your alerts."
        ),
        parse_mode="HTML",
    )
    logger.info("User %s set price alert on %s %s $%s", telegram_user_id, symbol, direction, target_price)


async def _handle_my_alerts(bot: Bot, update: Update) -> None:
    """/my-alerts — list active price alerts."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    from sqlalchemy import select
    from db import price_alert_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(price_alert_table)
            .where(
                price_alert_table.c.telegram_user_id == telegram_user_id,
                price_alert_table.c.status == "active",
            )
            .order_by(price_alert_table.c.created_at.desc())
        )
        alerts = result.fetchall()

    if not alerts:
        await bot.send_message(
            chat_id=chat_id,
            text="🔔 No active alerts. Use <code>/alert [token] [price]</code> to set one.",
            parse_mode="HTML",
        )
        return

    lines = [f"<b>Your Active Alerts ({len(alerts)})</b>\n"]
    for a in alerts:
        lines.append(f"🔔 <b>${a.symbol}</b> {a.direction} ${a.target_price:.6g}  [<code>{a.id[:8]}</code>]")
    lines.append("\nUse <code>/cancel-alert [id]</code> to remove one.")
    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")


async def _handle_cancel_alert(bot: Bot, update: Update) -> None:
    """/cancel-alert <id> — cancel a price alert by its short ID."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Usage: <code>/cancel-alert [id]</code>\nFind alert IDs with /my-alerts.",
            parse_mode="HTML",
        )
        return

    short_id = parts[1].lower()

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    from sqlalchemy import select, func
    from sqlalchemy import update as sa_update
    from db import price_alert_table, get_session
    async with get_session() as session:
        result = await session.execute(
            select(price_alert_table).where(
                price_alert_table.c.telegram_user_id == telegram_user_id,
                price_alert_table.c.status == "active",
                func.lower(price_alert_table.c.id).like(short_id + "%"),
            )
        )
        alert = result.fetchone()

    if not alert:
        await bot.send_message(chat_id=chat_id, text=f"❌ No active alert matching <code>{short_id}</code>.", parse_mode="HTML")
        return

    from datetime import datetime, timezone
    async with get_session() as session:
        await session.execute(
            sa_update(price_alert_table)
            .where(price_alert_table.c.id == alert.id)
            .values(status="cancelled")
        )

    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ Alert for <b>${alert.symbol}</b> {alert.direction} ${alert.target_price:.6g} cancelled.",
        parse_mode="HTML",
    )


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
        copy_score=78.0,
        consensus_count=2,
    )
    logger.info("Test alert triggered by chat %s", chat_id)


async def _handle_signal(bot: Bot, update: Update) -> None:
    """/signal <token_address> — show copy score + per-factor breakdown."""
    chat_id = update.message.chat.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/signal [token_address]</code>\n"
                "Returns a structured copy score breakdown.\n"
                "Example: <code>/signal DezXAZ8z7Pnr</code>"
            ),
            parse_mode="HTML",
        )
        return

    token_address = parts[1]
    thinking_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🔍 Fetching signal data for <code>{token_address[:16]}...</code>",
        parse_mode="HTML",
    )

    try:
        from services.enrichment import build_mini_report, _compute_copy_score, get_live_consensus
        report = await build_mini_report(token_address)
        cons_count = get_live_consensus(token_address)
        copy_score = _compute_copy_score(report, cons_count)

        symbol = report.symbol or token_address[:8]
        sec_str = f"{report.security_score:.0f}/100" if report.security_score is not None else "N/A"
        sm_str = "✅ Yes" if report.smart_money_flag else "No"
        mom_str = f"{report.momentum_24h:+.1f}%" if report.momentum_24h is not None else "N/A"
        liq_str = f"${report.total_liquidity_usd:,.0f}" if report.total_liquidity_usd is not None else "N/A"
        bsr_str = f"{report.buy_sell_ratio:.2f}" if report.buy_sell_ratio is not None else "N/A"

        # Verdict
        if copy_score >= 70:
            verdict = "✅ <b>COPY</b>"
        elif copy_score >= 50:
            verdict = "👀 <b>WATCH</b>"
        else:
            verdict = "🚫 <b>SKIP</b>"

        cs_emoji = "🟢" if copy_score >= 70 else ("🟡" if copy_score >= 50 else "🔴")
        token_url = f"https://birdeye.so/token/{token_address}?chain=solana"

        text = (
            f"📊 <b>Signal Report — <a href='{token_url}'>${symbol}</a></b>\n"
            f"\n"
            f"{cs_emoji} Copy Score: <b>{copy_score:.0f}/100</b>  →  {verdict}\n"
            f"\n"
            f"<b>Factor Breakdown:</b>\n"
            f"🔒 Security:      {sec_str} (25pts)\n"
            f"🧠 Smart Money:   {sm_str} (20pts)\n"
            f"📈 Momentum 24h:  {mom_str} (20pts)\n"
            f"📊 Buy/Sell Ratio:{bsr_str} (15pts)\n"
            f"💧 Liquidity:     {liq_str} (10pts)\n"
            f"🐋 Consensus:     {cons_count} whale(s) (10pts)\n"
        )

        if cons_count >= 2:
            text += f"\n💡 <b>{cons_count} whales bought this token in the last 2h</b>"

        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ Failed to fetch signal data: {exc}", parse_mode="HTML")
    finally:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=thinking_msg.message_id)
        except Exception:
            pass

    logger.info("Responded to /signal for %s from chat %s", token_address[:8], chat_id)


async def _handle_analyze(bot: Bot, update: Update) -> None:
    """/analyze <token_address> — full Groq AI analysis."""
    chat_id = update.message.chat.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/analyze [token_address]</code>\n"
                "Returns a full AI narrative analysis (takes ~20s).\n"
                "Example: <code>/analyze DezXAZ8z7Pnr</code>"
            ),
            parse_mode="HTML",
        )
        return

    token_address = parts[1]
    thinking_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🤖 <b>AI is analysing <code>{token_address[:16]}...</code></b>\nThis takes ~20 seconds...",
        parse_mode="HTML",
    )

    try:
        from services.enrichment import build_mini_report, _compute_copy_score, get_live_consensus
        from services.gemini import analyse_trade

        report = await build_mini_report(token_address)
        cons_count = get_live_consensus(token_address)
        copy_score = _compute_copy_score(report, cons_count)
        symbol = report.symbol or token_address[:8]

        result = await analyse_trade(
            token_symbol=symbol,
            token_address=token_address,
            side="BUY",
            usd_value=0.0,
            security_score=report.security_score,
            is_honeypot=report.is_honeypot,
            smart_money_flag=report.smart_money_flag,
            momentum_24h=report.momentum_24h,
            holder_count=report.holder_count,
            buy_sell_ratio=report.buy_sell_ratio,
            liquidity_usd=report.total_liquidity_usd,
            market_cap=report.market_cap,
            copy_score=copy_score,
            consensus_count=cons_count,
        )

        token_url = f"https://birdeye.so/token/{token_address}?chain=solana"

        if result:
            rec = result.get("recommendation", "HOLD")
            analysis = result.get("analysis", "")
            rec_emoji = {"STRONG_BUY": "🟢", "BUY": "🟩", "HOLD": "🟡", "SELL": "🟠", "AVOID": "🔴"}.get(rec, "⬜")
            rec_label = rec.replace("_", " ")
            text = (
                f"🤖 <b>AI Analysis — <a href='{token_url}'>${symbol}</a></b>\n"
                f"{rec_emoji} <b>{rec_label}</b>  |  Copy Score: {copy_score:.0f}/100\n\n"
                f"{analysis}"
            )
        else:
            text = (
                f"⚠️ <b>AI Analysis — <a href='{token_url}'>${symbol}</a></b>\n"
                f"Copy Score: {copy_score:.0f}/100\n\n"
                f"AI analysis unavailable right now (Groq quota or timeout). "
                f"Use /signal for a structured data-only breakdown."
            )

        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ Analysis failed: {exc}", parse_mode="HTML")
    finally:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=thinking_msg.message_id)
        except Exception:
            pass

    logger.info("Responded to /analyze for %s from chat %s", token_address[:8], chat_id)


async def _handle_trending(bot: Bot, update: Update) -> None:
    """/trending — show the top 5 trending tokens by Birdeye rank."""
    chat_id = update.message.chat.id
    try:
        from services import birdeye
        raw = await birdeye.get_token_trending(sort_by="rank", sort_type="asc", offset=0, limit=5)
        tokens = (raw.get("data") or {}).get("tokens") or []
    except Exception as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ Failed to fetch trending data: {exc}", parse_mode="HTML")
        return

    if not tokens:
        await bot.send_message(chat_id=chat_id, text="📊 No trending tokens available right now.", parse_mode="HTML")
        return

    lines = ["🔥 <b>Top 5 Trending on Solana</b>"]
    for token in tokens[:5]:
        addr = token.get("address", "")
        symbol = token.get("symbol") or addr[:8]
        price = token.get("price") or 0
        pct = token.get("priceChange24hPercent") or token.get("price24hChangePercent") or 0
        rank = token.get("rank") or "?"
        pct_str = f"{pct:+.2f}%" if pct else "—"
        pct_emoji = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⬜")
        price_str = f"${price:.6g}" if price and price < 1 else (f"${price:,.4f}" if price else "—")
        birdeye_url = f"https://birdeye.so/token/{addr}?chain=solana"
        lines.append(
            f"#{rank} <b>${symbol}</b>  <code>{price_str}</code>\n"
            f"24h: {pct_emoji} <b>{pct_str}</b> • <a href='{birdeye_url}'>View chart</a>"
        )

    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    logger.info("Responded to /trending from chat %s", chat_id)


async def _handle_new_listings(bot: Bot, update: Update) -> None:
    """/new-listings — show the 5 most recently created Solana tokens."""
    chat_id = update.message.chat.id
    try:
        from services import birdeye
        raw = await birdeye.get_new_listings(limit=5, offset=0)
        data = raw.get("data") or []
        if isinstance(data, dict):
            tokens = data.get("items") or []
        elif isinstance(data, list):
            tokens = data
        else:
            tokens = []
    except Exception as exc:
        await bot.send_message(chat_id=chat_id, text=f"❌ Failed to fetch new listings: {exc}", parse_mode="HTML")
        return

    if not tokens:
        await bot.send_message(chat_id=chat_id, text="📊 No new listings available right now.", parse_mode="HTML")
        return

    lines = ["🆕 <b>Newest Solana Listings (Top 5)</b>"]
    for idx, token in enumerate(tokens[:5], start=1):
        addr = token.get("address") or ""
        symbol = token.get("symbol") or addr[:8]
        name = token.get("name") or token.get("tokenName") or "Unknown Token"
        price = token.get("price") or 0
        pct = token.get("priceChange24hPercent") or token.get("price24hChangePercent") or 0
        pct_str = f"{pct:+.2f}%" if pct else "—"
        pct_emoji = "🟢" if pct > 0 else ("🔴" if pct < 0 else "⬜")
        price_str = f"${price:.6g}" if price and price < 1 else (f"${price:,.4f}" if price else "—")
        birdeye_url = f"https://birdeye.so/token/{addr}?chain=solana"
        safe_symbol = html.escape(str(symbol), quote=False)
        safe_name = html.escape(str(name), quote=False)
        lines.append(
            f"#{idx} <b>${safe_symbol}</b> — {safe_name}\n"
            f"Price: <code>{price_str}</code>\n"
            f"24h: {pct_emoji} <b>{pct_str}</b> • <a href='{birdeye_url}'>View chart</a>"
        )

    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    logger.info("Responded to /new-listings from chat %s", chat_id)


async def _handle_close_trade(bot: Bot, update: Update) -> None:
    """/close-trade <id> — manually close an open paper trade at current price."""
    chat_id = update.message.chat.id
    telegram_user_id = update.message.from_user.id
    parts = (update.message.text or "").strip().split()

    if len(parts) < 2:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "ℹ️ Usage: <code>/close-trade [id]</code>\n"
                "Find trade IDs with /my-trades."
            ),
            parse_mode="HTML",
        )
        return

    short_id = parts[1].lower()

    import db
    if not db.is_available():
        await bot.send_message(chat_id=chat_id, text="⚠️ Database not available.", parse_mode="HTML")
        return

    from sqlalchemy import func, update as sa_update
    from db import paper_trade_table, get_session
    from datetime import datetime, timezone

    # Find the trade by short ID prefix, scoped to this user
    async with get_session() as session:
        result = await session.execute(
            select(paper_trade_table).where(
                paper_trade_table.c.telegram_user_id == telegram_user_id,
                paper_trade_table.c.status == "open",
                func.lower(paper_trade_table.c.id).like(short_id + "%"),
            )
        )
        trade = result.fetchone()

    if not trade:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ No open trade found matching <code>{short_id}</code>.\nUse /my-trades to see your open positions.",
            parse_mode="HTML",
        )
        return

    # Fetch current price
    try:
        from services import birdeye
        raw = await birdeye.get_token_price(trade.token_address)
        current_price = float((raw.get("data") or {}).get("value") or 0)
    except Exception:
        current_price = None

    if not current_price:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Could not fetch current price. Try again in a moment.",
            parse_mode="HTML",
        )
        return

    entry = trade.entry_price
    pnl_pct = round(((current_price - entry) / entry) * 100, 2)
    if trade.side == "SELL":
        pnl_pct = -pnl_pct

    now = datetime.now(tz=timezone.utc)
    async with get_session() as session:
        await session.execute(
            sa_update(paper_trade_table)
            .where(paper_trade_table.c.id == trade.id)
            .values(
                status="closed",
                exit_price=current_price,
                exit_time=now,
                pnl_pct=pnl_pct,
                close_reason="manual",
            )
        )

    sign = "+" if pnl_pct >= 0 else ""
    symbol = trade.symbol or trade.token_address[:8]
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⚪ <b>Trade closed — ${symbol}</b>\n\n"
            f"Side: {trade.side}\n"
            f"Entry: ${entry:.6g}  →  Exit: ${current_price:.6g}\n"
            f"P&L: <b>{sign}{pnl_pct:.2f}%</b>  (manual close)\n\n"
            f"Use /my-trades to see your full history."
        ),
        parse_mode="HTML",
    )
    logger.info("User %s manually closed trade %s on %s P&L=%.2f%%", telegram_user_id, trade.id[:8], symbol, pnl_pct)


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
    elif text.startswith("/track ") or text == "/track":
        await _handle_track(bot, update)
    elif text.startswith("/my-trades") or text == "/my-trades":
        await _handle_my_trades(bot, update)
    elif text.startswith("/alert ") or text == "/alert":
        await _handle_alert(bot, update)
    elif text.startswith("/my-alerts") or text == "/my-alerts":
        await _handle_my_alerts(bot, update)
    elif text.startswith("/cancel-alert ") or text == "/cancel-alert":
        await _handle_cancel_alert(bot, update)
    elif text.startswith("/test_alert") or text == "/test_alert":
        await _handle_test_alert(bot, update)
    elif text.startswith("/signal ") or text == "/signal":
        await _handle_signal(bot, update)
    elif text.startswith("/analyze ") or text == "/analyze":
        await _handle_analyze(bot, update)
    elif text.startswith("/close-trade ") or text == "/close-trade":
        await _handle_close_trade(bot, update)
    elif text.startswith("/trending") or text.startswith("/trendings"):
        await _handle_trending(bot, update)
    elif (
        text.startswith("/new-listings")
        or text.startswith("/new_listings")
        or text.startswith("/newlisting")
        or text.startswith("/new-listing")
        or text.startswith("/newlistings")
    ):
        await _handle_new_listings(bot, update)
    # Unknown commands silently ignored


async def _register_commands(bot: Bot) -> None:
    """Register bot commands so they show in Telegram's command menu."""
    try:
        commands = [
            BotCommand("start", "Welcome + command overview"),
            BotCommand("wallets", "List tracked whale wallets"),
            BotCommand("stats", "Show aggregate wallet stats"),
            BotCommand("top", "Top wallets by PnL"),
            BotCommand("signal", "Data-only token signal breakdown"),
            BotCommand("analyze", "AI token analysis (Groq)"),
            BotCommand("trending", "Top 5 trending tokens"),
            BotCommand("newlisting", "5 newest token launches"),
            BotCommand("help", "Show all commands"),
        ]
        # Register in both default and private scopes so commands appear reliably.
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Telegram bot command menu registered.")
    except Exception as exc:
        logger.warning("Failed to register Telegram commands: %s", exc)


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

    await _register_commands(bot)
    logger.info("Telegram command loop started — listening for /start, /wallets, /stats, /top, /wallet, /filter, /watch, /unwatch, /my-wallets, /track, /my-trades, /alert, /my-alerts, /cancel-alert, /signal, /analyze, /close-trade, /trending, /trendings, /newlisting, /new-listings, /newlistings, /help")
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
