"""
Telegram bot — 6 priority feature tests.

Covers:
  Priority 1 — Daily Alpha Briefing  (_build_briefing_data, send_daily_briefing)
  Priority 2 — Signal report         (_handle_signal)
  Priority 3 — AI analysis           (_handle_analyze)
  Priority 4 — Paper trading         (_handle_track, _handle_my_trades, _handle_close_trade)
  Priority 5 — Price alerts          (_handle_alert, _handle_my_alerts, _handle_cancel_alert)
  Priority 6 — Discovery commands    (_handle_trending, _handle_new_listings, _handle_holdings)

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_telegram_bot.py -v
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_update(text: str, chat_id: int = 111, user_id: int = 999) -> MagicMock:
    """Build a minimal Telegram Update mock from a command string."""
    update = MagicMock()
    update.message.text = text
    update.message.chat.id = chat_id
    update.message.from_user.id = user_id
    return update


def _make_bot() -> MagicMock:
    """Return a bot mock where all send/delete operations are async no-ops."""
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
    bot.delete_message = AsyncMock()
    return bot


def _fake_trade_rows(
    *,
    token_address: str = "TOKAAAA",
    wallet_id: str = "WALAAAA",
    side: str = "BUY",
    usd_value: float = 1000.0,
    n: int = 3,
) -> list[MagicMock]:
    rows = []
    for i in range(n):
        r = MagicMock()
        r.token_address = token_address
        r.token_symbol = "BONK"
        r.wallet_id = wallet_id
        r.side = side
        r.usd_value = usd_value
        r.timestamp = datetime.now(tz=timezone.utc) - timedelta(hours=i)
        rows.append(r)
    return rows


# ─── Priority 1: Daily Alpha Briefing ─────────────────────────────────────────


class TestBuildBriefingData:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        from services.telegram import _build_briefing_data

        fake_rows = _fake_trade_rows(n=5)
        fake_result = MagicMock()
        fake_result.fetchall.return_value = fake_rows

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.get_session", return_value=fake_session), \
                 patch("services.signal_stats.get_cached_stats", return_value=None):
            data = await _build_briefing_data()

        required_keys = {
            "total_trades", "buy_count", "sell_count",
            "total_volume_usd", "accumulation_tokens", "exit_tokens", "best_signal",
        }
        assert required_keys.issubset(data.keys())

    @pytest.mark.asyncio
    async def test_counts_buys_and_sells_correctly(self):
        from services.telegram import _build_briefing_data

        buy_rows = _fake_trade_rows(side="BUY", n=4)
        sell_rows = _fake_trade_rows(side="SELL", n=2, wallet_id="WALSELL")
        all_rows = buy_rows + sell_rows

        fake_result = MagicMock()
        fake_result.fetchall.return_value = all_rows

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.get_session", return_value=fake_session), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            data = await _build_briefing_data()

        assert data["total_trades"] == 6
        assert data["buy_count"] == 4
        assert data["sell_count"] == 2
        assert data["total_volume_usd"] == pytest.approx(6 * 1000.0)

    @pytest.mark.asyncio
    async def test_best_signal_populated_from_stats_cache(self):
        from services.telegram import _build_briefing_data

        fake_rows = _fake_trade_rows(n=2)
        fake_result = MagicMock()
        fake_result.fetchall.return_value = fake_rows

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.get_session", return_value=fake_session), \
             patch("services.signal_stats.get_cached_stats", return_value={
                 "top_performers": [{"symbol": "WIF", "return_pct": 42.0}]
             }):
            data = await _build_briefing_data()

        assert data["best_signal"] is not None
        assert data["best_signal"]["symbol"] == "WIF"
        assert data["best_signal"]["return_pct"] == pytest.approx(42.0)

    @pytest.mark.asyncio
    async def test_returns_empty_best_signal_when_no_stats(self):
        from services.telegram import _build_briefing_data

        fake_result = MagicMock()
        fake_result.fetchall.return_value = []

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.get_session", return_value=fake_session), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            data = await _build_briefing_data()

        assert data["best_signal"] is None


class TestSendDailyBriefing:
    @pytest.mark.asyncio
    async def test_sends_message_when_trades_exist(self):
        bot = _make_bot()
        fake_data = {
            "total_trades": 10,
            "buy_count": 7,
            "sell_count": 3,
            "total_volume_usd": 25000.0,
            "accumulation_tokens": [{"symbol": "BONK", "wallet_count": 3, "total_usd": 9000.0}],
            "exit_tokens": [],
            "best_signal": None,
        }
        sm_raw = {"data": {"items": [{"symbol": "WIF", "address": "WIF1", "priceChange24hPercent": 12.5}]}}
        trend_raw = {"data": {"tokens": [{"symbol": "BOME", "address": "BOME1", "rank": 1, "priceChange24hPercent": 5.0}]}}
        gl_raw = {"data": {"items": [{"symbol": "DOGE", "address": "DOGE1", "pnl": 50000.0}]}}

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="@testchan"), \
             patch("services.telegram._build_briefing_data", new=AsyncMock(return_value=fake_data)), \
             patch("services.gemini.analyse_daily_briefing", new=AsyncMock(return_value="Market is bullish.")), \
             patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=sm_raw)), \
             patch("services.birdeye.get_token_trending", new=AsyncMock(return_value=trend_raw)), \
             patch("services.birdeye.get_gainers_losers", new=AsyncMock(return_value=gl_raw)):
            from services.telegram import send_daily_briefing
            await send_daily_briefing()

        bot.send_message.assert_called_once()
        sent_text = bot.send_message.call_args.kwargs["text"]
        assert "ZENTRYX DAILY BRIEFING" in sent_text
        assert "10 whale trades" in sent_text
        assert "BONK" in sent_text
        assert "WIF" in sent_text
        assert "BOME" in sent_text
        assert "Market is bullish." in sent_text

    @pytest.mark.asyncio
    async def test_sends_quiet_message_when_no_trades(self):
        bot = _make_bot()
        fake_data = {
            "total_trades": 0,
            "buy_count": 0,
            "sell_count": 0,
            "total_volume_usd": 0.0,
            "accumulation_tokens": [],
            "exit_tokens": [],
            "best_signal": None,
        }

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="@testchan"), \
             patch("services.telegram._build_briefing_data", new=AsyncMock(return_value=fake_data)):
            from services.telegram import send_daily_briefing
            await send_daily_briefing()

        bot.send_message.assert_called_once()
        assert "Quiet market day" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_skips_when_not_configured(self):
        with patch("services.telegram._get_bot", return_value=None), \
             patch("services.telegram._group_chat_id", return_value=None):
            from services.telegram import send_daily_briefing
            # Should not raise
            await send_daily_briefing()

    @pytest.mark.asyncio
    async def test_briefing_gracefully_excludes_ai_on_failure(self):
        bot = _make_bot()
        fake_data = {
            "total_trades": 5,
            "buy_count": 5,
            "sell_count": 0,
            "total_volume_usd": 5000.0,
            "accumulation_tokens": [{"symbol": "SOL", "wallet_count": 2, "total_usd": 5000.0}],
            "exit_tokens": [],
            "best_signal": None,
        }

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="@testchan"), \
             patch("services.telegram._build_briefing_data", new=AsyncMock(return_value=fake_data)), \
             patch("services.gemini.analyse_daily_briefing", new=AsyncMock(return_value=None)), \
             patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(side_effect=Exception("API down"))), \
             patch("services.birdeye.get_token_trending", new=AsyncMock(side_effect=Exception("API down"))), \
             patch("services.birdeye.get_gainers_losers", new=AsyncMock(side_effect=Exception("API down"))):
            from services.telegram import send_daily_briefing
            await send_daily_briefing()

        bot.send_message.assert_called_once()
        sent_text = bot.send_message.call_args.kwargs["text"]
        # Should still send the DB-based briefing without AI
        assert "5 whale trades" in sent_text


# ─── Priority 2: Signal Report ────────────────────────────────────────────────


class TestHandleSignal:
    @pytest.mark.asyncio
    async def test_returns_signal_report(self):
        bot = _make_bot()
        update = _make_update("/signal So11111111111111111111111111111111111111112")

        fake_report = MagicMock()
        fake_report.symbol = "SOL"
        fake_report.security_score = 85.0
        fake_report.smart_money_flag = True
        fake_report.momentum_24h = 4.2
        fake_report.total_liquidity_usd = 500000.0
        fake_report.buy_sell_ratio = 1.4

        with patch("services.enrichment.build_mini_report", new=AsyncMock(return_value=fake_report)), \
             patch("services.enrichment.get_live_consensus", return_value=3), \
             patch("services.enrichment._compute_copy_score", return_value=78.0):
            from services.telegram import _handle_signal
            await _handle_signal(bot, update)

        bot.send_message.assert_called()
        sent_text = bot.send_message.call_args_list[-1].kwargs["text"]
        assert "Signal Report" in sent_text
        assert "78" in sent_text  # copy score
        assert "SOL" in sent_text

    @pytest.mark.asyncio
    async def test_shows_usage_when_no_args(self):
        bot = _make_bot()
        update = _make_update("/signal")

        from services.telegram import _handle_signal
        await _handle_signal(bot, update)

        bot.send_message.assert_called_once()
        assert "Usage" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_shows_error_on_exception(self):
        bot = _make_bot()
        update = _make_update("/signal BADINPUT")

        with patch("services.enrichment.build_mini_report", new=AsyncMock(side_effect=Exception("API error"))):
            from services.telegram import _handle_signal
            await _handle_signal(bot, update)

        # Final message should be an error message
        assert any("Failed" in str(c.kwargs.get("text", "")) for c in bot.send_message.call_args_list)

    @pytest.mark.asyncio
    async def test_high_copy_score_shows_copy_verdict(self):
        bot = _make_bot()
        update = _make_update("/signal HIGHSCORE123")

        fake_report = MagicMock()
        fake_report.symbol = "WIF"
        fake_report.security_score = 90.0
        fake_report.smart_money_flag = True
        fake_report.momentum_24h = 12.0
        fake_report.total_liquidity_usd = 1000000.0
        fake_report.buy_sell_ratio = 2.1

        with patch("services.enrichment.build_mini_report", new=AsyncMock(return_value=fake_report)), \
             patch("services.enrichment.get_live_consensus", return_value=4), \
             patch("services.enrichment._compute_copy_score", return_value=85.0):
            from services.telegram import _handle_signal
            await _handle_signal(bot, update)

        sent_text = bot.send_message.call_args_list[-1].kwargs["text"]
        assert "COPY" in sent_text

    @pytest.mark.asyncio
    async def test_low_copy_score_shows_skip_verdict(self):
        bot = _make_bot()
        update = _make_update("/signal LOWSCORE123")

        fake_report = MagicMock()
        fake_report.symbol = "RUG"
        fake_report.security_score = 10.0
        fake_report.smart_money_flag = False
        fake_report.momentum_24h = -45.0
        fake_report.total_liquidity_usd = 5000.0
        fake_report.buy_sell_ratio = 0.3

        with patch("services.enrichment.build_mini_report", new=AsyncMock(return_value=fake_report)), \
             patch("services.enrichment.get_live_consensus", return_value=0), \
             patch("services.enrichment._compute_copy_score", return_value=18.0):
            from services.telegram import _handle_signal
            await _handle_signal(bot, update)

        sent_text = bot.send_message.call_args_list[-1].kwargs["text"]
        assert "SKIP" in sent_text


# ─── Priority 3: AI Analysis ──────────────────────────────────────────────────


class TestHandleAnalyze:
    @pytest.mark.asyncio
    async def test_returns_ai_analysis(self):
        bot = _make_bot()
        update = _make_update("/analyze SOLADDRESS123")

        fake_report = MagicMock()
        fake_report.symbol = "BONK"
        fake_report.security_score = 70.0
        fake_report.is_honeypot = False
        fake_report.smart_money_flag = True
        fake_report.momentum_24h = 8.0
        fake_report.holder_count = 50000
        fake_report.buy_sell_ratio = 1.6
        fake_report.total_liquidity_usd = 750000.0
        fake_report.market_cap = 1000000.0

        fake_ai = {"recommendation": "BUY", "analysis": "Strong fundamentals and growing adoption."}

        with patch("services.enrichment.build_mini_report", new=AsyncMock(return_value=fake_report)), \
             patch("services.enrichment.get_live_consensus", return_value=2), \
             patch("services.enrichment._compute_copy_score", return_value=72.0), \
             patch("services.gemini.analyse_trade", new=AsyncMock(return_value=fake_ai)):
            from services.telegram import _handle_analyze
            await _handle_analyze(bot, update)

        sent_texts = [c.kwargs.get("text", "") for c in bot.send_message.call_args_list]
        final = sent_texts[-1]
        assert "AI Analysis" in final
        assert "Strong fundamentals" in final
        assert "BUY" in final

    @pytest.mark.asyncio
    async def test_shows_usage_when_no_args(self):
        bot = _make_bot()
        update = _make_update("/analyze")

        from services.telegram import _handle_analyze
        await _handle_analyze(bot, update)

        bot.send_message.assert_called_once()
        assert "Usage" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_graceful_when_ai_unavailable(self):
        bot = _make_bot()
        update = _make_update("/analyze TOKENADDR123")

        fake_report = MagicMock()
        fake_report.symbol = "TEST"
        fake_report.security_score = 60.0
        fake_report.is_honeypot = False
        fake_report.smart_money_flag = False
        fake_report.momentum_24h = 0.0
        fake_report.holder_count = 1000
        fake_report.buy_sell_ratio = 1.0
        fake_report.total_liquidity_usd = 50000.0
        fake_report.market_cap = 100000.0

        with patch("services.enrichment.build_mini_report", new=AsyncMock(return_value=fake_report)), \
             patch("services.enrichment.get_live_consensus", return_value=0), \
             patch("services.enrichment._compute_copy_score", return_value=45.0), \
             patch("services.gemini.analyse_trade", new=AsyncMock(return_value=None)):
            from services.telegram import _handle_analyze
            await _handle_analyze(bot, update)

        sent_texts = [c.kwargs.get("text", "") for c in bot.send_message.call_args_list]
        final = sent_texts[-1]
        assert "AI analysis unavailable" in final or "Copy Score" in final


# ─── Priority 4: Paper Trading ────────────────────────────────────────────────


class TestHandleTrack:
    @pytest.mark.asyncio
    async def test_opens_paper_trade(self):
        bot = _make_bot()
        update = _make_update("/track WIF 40 15")
        update.message.text = "/track WIF 40 15"

        price_raw = {"data": {"value": 2.50}}

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock()

        with patch("db.is_available", return_value=True), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value=price_raw)), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_track
            await _handle_track(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "Paper trade opened" in sent or "WIF" in sent

    @pytest.mark.asyncio
    async def test_shows_usage_when_missing_token(self):
        bot = _make_bot()
        update = _make_update("/track")

        from services.telegram import _handle_track
        await _handle_track(bot, update)

        bot.send_message.assert_called_once()
        assert "Usage" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_rejects_when_db_unavailable(self):
        bot = _make_bot()
        update = _make_update("/track BONK 30 10")

        price_raw = {"data": {"value": 0.001}}
        # _handle_track fetches price first, then checks DB
        with patch("services.birdeye.get_token_price", new=AsyncMock(return_value=price_raw)), \
             patch("services.birdeye.get_token_overview", new=AsyncMock(return_value={"data": {"symbol": "BONK"}})), \
             patch("db.is_available", return_value=False):
            from services.telegram import _handle_track
            await _handle_track(bot, update)

        assert "Database" in bot.send_message.call_args.kwargs["text"] or \
               "not available" in bot.send_message.call_args.kwargs["text"].lower()


class TestHandleMyTrades:
    @pytest.mark.asyncio
    async def test_shows_open_trades(self):
        bot = _make_bot()
        update = _make_update("/my-trades")

        fake_trade = MagicMock()
        fake_trade.symbol = "SOL"
        fake_trade.side = "BUY"
        fake_trade.entry_price = 150.0
        fake_trade.tp_pct = 40.0
        fake_trade.sl_pct = 15.0
        fake_trade.status = "open"
        fake_trade.pnl_pct = None
        fake_trade.created_at = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        fake_trade.id = "trade-uuid-001"
        fake_trade.token_address = "SOL111"

        fake_result = MagicMock()
        fake_result.fetchall.return_value = [fake_trade]

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        price_raw = {"data": {"value": 180.0}}

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value=price_raw)):
            from services.telegram import _handle_my_trades
            await _handle_my_trades(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "SOL" in sent

    @pytest.mark.asyncio
    async def test_shows_empty_when_no_trades(self):
        bot = _make_bot()
        update = _make_update("/my-trades")

        fake_result = MagicMock()
        fake_result.fetchall.return_value = []

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_my_trades
            await _handle_my_trades(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "no" in sent.lower() or "empty" in sent.lower() or "track" in sent.lower()


class TestHandleCloseTrade:
    @pytest.mark.asyncio
    async def test_closes_open_trade_and_reports_pnl(self):
        bot = _make_bot()
        update = _make_update("/close-trade trade-u")

        fake_trade = MagicMock()
        fake_trade.id = "trade-uuid-001"
        fake_trade.symbol = "WIF"
        fake_trade.side = "BUY"
        fake_trade.entry_price = 2.00
        fake_trade.token_address = "WIF111"

        find_result = MagicMock()
        find_result.fetchone.return_value = fake_trade

        update_result = MagicMock()

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(side_effect=[find_result, update_result])

        price_raw = {"data": {"value": 2.50}}

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value=price_raw)):
            from services.telegram import _handle_close_trade
            await _handle_close_trade(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "WIF" in sent
        assert "P&L" in sent or "closed" in sent.lower()

    @pytest.mark.asyncio
    async def test_shows_error_when_trade_not_found(self):
        bot = _make_bot()
        update = _make_update("/close-trade notreal")

        find_result = MagicMock()
        find_result.fetchone.return_value = None

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=find_result)

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_close_trade
            await _handle_close_trade(bot, update)

        bot.send_message.assert_called()
        assert "❌" in bot.send_message.call_args.kwargs["text"] or \
               "No open trade" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_shows_usage_when_no_id(self):
        bot = _make_bot()
        update = _make_update("/close-trade")

        with patch("db.is_available", return_value=True):
            from services.telegram import _handle_close_trade
            await _handle_close_trade(bot, update)

        assert "Usage" in bot.send_message.call_args.kwargs["text"]


# ─── Priority 5: Price Alerts ─────────────────────────────────────────────────


class TestHandleAlert:
    @pytest.mark.asyncio
    async def test_creates_alert_above(self):
        bot = _make_bot()
        update = _make_update("/alert BONK 0.0005 above")

        price_raw = {"data": {"value": 0.0003}}

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock()

        with patch("db.is_available", return_value=True), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value=price_raw)), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_alert
            await _handle_alert(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "BONK" in sent or "alert" in sent.lower()

    @pytest.mark.asyncio
    async def test_shows_usage_when_missing_args(self):
        bot = _make_bot()
        update = _make_update("/alert BONK")

        from services.telegram import _handle_alert
        await _handle_alert(bot, update)

        bot.send_message.assert_called_once()
        assert "Usage" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_rejects_when_db_unavailable(self):
        bot = _make_bot()
        update = _make_update("/alert SOL 200 above")

        with patch("db.is_available", return_value=False):
            from services.telegram import _handle_alert
            await _handle_alert(bot, update)

        assert "Database" in bot.send_message.call_args.kwargs["text"] or \
               "not available" in bot.send_message.call_args.kwargs["text"].lower()


class TestHandleMyAlerts:
    @pytest.mark.asyncio
    async def test_shows_active_alerts(self):
        bot = _make_bot()
        update = _make_update("/my-alerts")

        fake_alert = MagicMock()
        fake_alert.symbol = "SOL"
        fake_alert.direction = "above"
        fake_alert.target_price = 200.0
        fake_alert.id = "alert-uuid-001"

        fake_result = MagicMock()
        fake_result.fetchall.return_value = [fake_alert]

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_my_alerts
            await _handle_my_alerts(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "SOL" in sent

    @pytest.mark.asyncio
    async def test_shows_empty_state_when_no_alerts(self):
        bot = _make_bot()
        update = _make_update("/my-alerts")

        fake_result = MagicMock()
        fake_result.fetchall.return_value = []

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=fake_result)

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_my_alerts
            await _handle_my_alerts(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "no" in sent.lower() or "alert" in sent.lower()


class TestHandleCancelAlert:
    @pytest.mark.asyncio
    async def test_cancels_matching_alert(self):
        bot = _make_bot()
        update = _make_update("/cancel-alert alert-u")

        fake_alert = MagicMock()
        fake_alert.id = "alert-uuid-001"
        fake_alert.symbol = "SOL"
        fake_alert.direction = "above"
        fake_alert.target_price = 200.0

        find_result = MagicMock()
        find_result.fetchone.return_value = fake_alert

        update_result = MagicMock()

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(side_effect=[find_result, update_result])

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_cancel_alert
            await _handle_cancel_alert(bot, update)

        bot.send_message.assert_called()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "SOL" in sent and "cancel" in sent.lower()

    @pytest.mark.asyncio
    async def test_shows_error_when_alert_not_found(self):
        bot = _make_bot()
        update = _make_update("/cancel-alert notreal")

        find_result = MagicMock()
        find_result.fetchone.return_value = None

        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        fake_session.execute = AsyncMock(return_value=find_result)

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", return_value=fake_session):
            from services.telegram import _handle_cancel_alert
            await _handle_cancel_alert(bot, update)

        assert "❌" in bot.send_message.call_args.kwargs["text"] or \
               "No active alert" in bot.send_message.call_args.kwargs["text"]


# ─── Priority 6: Discovery Commands ──────────────────────────────────────────


class TestHandleTrending:
    @pytest.mark.asyncio
    async def test_shows_top_5_trending(self):
        bot = _make_bot()
        update = _make_update("/trending")

        tokens = [
            {"address": f"ADDR{i}", "symbol": f"TOK{i}", "rank": i,
             "price": 0.01 * i, "priceChange24hPercent": 5.0 * i}
            for i in range(1, 6)
        ]
        raw = {"data": {"tokens": tokens}}

        with patch("services.birdeye.get_token_trending", new=AsyncMock(return_value=raw)):
            from services.telegram import _handle_trending
            await _handle_trending(bot, update)

        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "Trending" in sent
        assert "TOK1" in sent

    @pytest.mark.asyncio
    async def test_shows_empty_when_no_trending(self):
        bot = _make_bot()
        update = _make_update("/trending")

        with patch("services.birdeye.get_token_trending", new=AsyncMock(return_value={"data": {"tokens": []}})):
            from services.telegram import _handle_trending
            await _handle_trending(bot, update)

        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "No trending" in sent or "available" in sent.lower()

    @pytest.mark.asyncio
    async def test_handles_birdeye_error_gracefully(self):
        bot = _make_bot()
        update = _make_update("/trending")

        with patch("services.birdeye.get_token_trending", new=AsyncMock(side_effect=Exception("API down"))):
            from services.telegram import _handle_trending
            await _handle_trending(bot, update)

        bot.send_message.assert_called_once()
        assert "Failed" in bot.send_message.call_args.kwargs["text"]


class TestHandleNewListings:
    @pytest.mark.asyncio
    async def test_shows_5_new_listings(self):
        bot = _make_bot()
        update = _make_update("/new-listings")

        tokens = [
            {"address": f"ADDR{i}", "symbol": f"NEW{i}", "name": f"NewToken {i}",
             "price": 0.001 * i, "priceChange24hPercent": 10.0}
            for i in range(1, 6)
        ]
        raw = {"data": {"items": tokens}}

        with patch("services.birdeye.get_new_listings", new=AsyncMock(return_value=raw)):
            from services.telegram import _handle_new_listings
            await _handle_new_listings(bot, update)

        bot.send_message.assert_called_once()
        sent = bot.send_message.call_args.kwargs["text"]
        assert "Listings" in sent
        assert "NEW1" in sent

    @pytest.mark.asyncio
    async def test_shows_empty_when_no_listings(self):
        bot = _make_bot()
        update = _make_update("/new-listings")

        with patch("services.birdeye.get_new_listings", new=AsyncMock(return_value={"data": {"items": []}})):
            from services.telegram import _handle_new_listings
            await _handle_new_listings(bot, update)

        bot.send_message.assert_called_once()
        assert "No new listings" in bot.send_message.call_args.kwargs["text"] or \
               "available" in bot.send_message.call_args.kwargs["text"].lower()

    @pytest.mark.asyncio
    async def test_handles_birdeye_error_gracefully(self):
        bot = _make_bot()
        update = _make_update("/new-listings")

        with patch("services.birdeye.get_new_listings", new=AsyncMock(side_effect=Exception("API down"))):
            from services.telegram import _handle_new_listings
            await _handle_new_listings(bot, update)

        assert "Failed" in bot.send_message.call_args.kwargs["text"]


class TestHandleHoldings:
    @pytest.mark.asyncio
    async def test_shows_whale_holders_by_symbol(self):
        bot = _make_bot()
        update = _make_update("/holdings BONK")

        whale = MagicMock()
        whale.address = "WHAL1111"
        whale.label = "Whale Alpha"

        portfolio_raw = {
            "data": {"items": [
                {"symbol": "BONK", "valueUsd": 25000.0, "address": "BONK111"}
            ]}
        }

        with patch("services.wallet_discovery.tracked_wallets", {"WHAL1111": whale}), \
             patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=portfolio_raw)):
            from services.telegram import _handle_holdings
            await _handle_holdings(bot, update)

        # There are 2 send_message calls: "checking..." and the result
        calls = bot.send_message.call_args_list
        final = calls[-1].kwargs["text"]
        assert "Whale Alpha" in final
        assert "BONK" in final

    @pytest.mark.asyncio
    async def test_shows_empty_when_no_holders(self):
        bot = _make_bot()
        update = _make_update("/holdings UNKNOWNTOKEN")

        whale = MagicMock()
        whale.address = "WHAL1111"
        whale.label = "Whale Alpha"

        portfolio_raw = {
            "data": {"items": [
                {"symbol": "SOL", "valueUsd": 5000.0, "address": "SOL1111"}
            ]}
        }

        with patch("services.wallet_discovery.tracked_wallets", {"WHAL1111": whale}), \
             patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=portfolio_raw)):
            from services.telegram import _handle_holdings
            await _handle_holdings(bot, update)

        calls = bot.send_message.call_args_list
        final = calls[-1].kwargs["text"]
        assert "No tracked whales" in final or "❌" in final

    @pytest.mark.asyncio
    async def test_shows_usage_when_no_token_arg(self):
        bot = _make_bot()
        update = _make_update("/holdings")

        from services.telegram import _handle_holdings
        await _handle_holdings(bot, update)

        bot.send_message.assert_called_once()
        assert "Usage" in bot.send_message.call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_shows_empty_when_no_tracked_wallets(self):
        bot = _make_bot()
        update = _make_update("/holdings BONK")

        with patch("services.wallet_discovery.tracked_wallets", {}):
            from services.telegram import _handle_holdings
            await _handle_holdings(bot, update)

        bot.send_message.assert_called_once()
        assert "No tracked wallets" in bot.send_message.call_args.kwargs["text"]
