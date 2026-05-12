"""
Day 10 functional tests — AI Daily Market Briefing.

Tests:
  1-2.  _build_briefing_data: correct aggregation, zero-row case
  3-7.  send_daily_briefing: happy path, Groq fail, zero trades, no exits, no best_signal
  8-9.  analyse_daily_briefing: prompt sent to Groq, Groq unavailable → None
  10.   scheduler has daily_briefing job at hour=9

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day10.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.telegram import _build_briefing_data, send_daily_briefing
from services.gemini import analyse_daily_briefing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(side="BUY", symbol="BONK", address="tokenA", wallet_id="w1", usd=1000.0, ts=None):
    from datetime import datetime, timezone, timedelta
    row = MagicMock()
    row.side = side
    row.token_symbol = symbol
    row.token_address = address
    row.wallet_id = wallet_id
    row.usd_value = usd
    row.timestamp = ts or (datetime.now(tz=timezone.utc) - timedelta(hours=1))
    return row


def _make_bot():
    bot = AsyncMock()
    msg = MagicMock()
    msg.message_id = 1
    bot.send_message.return_value = msg
    return bot


# ---------------------------------------------------------------------------
# 1. _build_briefing_data — correct aggregation
# ---------------------------------------------------------------------------

class TestBuildBriefingData:
    @pytest.mark.asyncio
    async def test_correct_aggregation(self):
        rows = [
            _make_row(side="BUY",  symbol="BONK", address="tA", wallet_id="w1", usd=500.0),
            _make_row(side="BUY",  symbol="BONK", address="tA", wallet_id="w2", usd=700.0),
            _make_row(side="BUY",  symbol="WIF",  address="tB", wallet_id="w1", usd=200.0),
            _make_row(side="SELL", symbol="JELLY", address="tC", wallet_id="w3", usd=300.0),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.get_session", return_value=mock_ctx), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            data = await _build_briefing_data()

        assert data["total_trades"] == 4
        assert data["buy_count"] == 3
        assert data["sell_count"] == 1
        assert data["total_volume_usd"] == pytest.approx(1700.0)

        # BONK should be top accumulation (2 unique wallets)
        assert data["accumulation_tokens"][0]["symbol"] == "BONK"
        assert data["accumulation_tokens"][0]["wallet_count"] == 2
        assert data["accumulation_tokens"][0]["total_usd"] == pytest.approx(1200.0)

        # Exit tokens — JELLY
        assert data["exit_tokens"][0]["symbol"] == "JELLY"
        assert data["exit_tokens"][0]["wallet_count"] == 1

    @pytest.mark.asyncio
    async def test_zero_rows(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.get_session", return_value=mock_ctx), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            data = await _build_briefing_data()

        assert data["total_trades"] == 0
        assert data["buy_count"] == 0
        assert data["sell_count"] == 0
        assert data["total_volume_usd"] == pytest.approx(0.0)
        assert data["accumulation_tokens"] == []
        assert data["exit_tokens"] == []
        assert data["best_signal"] is None

    @pytest.mark.asyncio
    async def test_best_signal_from_cache(self):
        rows = [_make_row()]
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        cached = {
            "top_performers": [{"symbol": "FOXY", "return_pct": 43.2}]
        }
        with patch("db.get_session", return_value=mock_ctx), \
             patch("services.signal_stats.get_cached_stats", return_value=cached):
            data = await _build_briefing_data()

        assert data["best_signal"] is not None
        assert data["best_signal"]["symbol"] == "FOXY"
        assert data["best_signal"]["return_pct"] == pytest.approx(43.2)


# ---------------------------------------------------------------------------
# 3-7. send_daily_briefing — functional tests
# ---------------------------------------------------------------------------

class TestSendDailyBriefing:
    def _full_data(self, **kwargs):
        d = {
            "total_trades": 42,
            "buy_count": 28,
            "sell_count": 14,
            "total_volume_usd": 1_840_000.0,
            "accumulation_tokens": [
                {"symbol": "BONK", "wallet_count": 4, "total_usd": 820_000},
                {"symbol": "WIF",  "wallet_count": 2, "total_usd": 340_000},
                {"symbol": "FOXY", "wallet_count": 1, "total_usd": 50_000},
            ],
            "exit_tokens": [
                {"symbol": "JELLY", "wallet_count": 3, "total_usd": 200_000},
            ],
            "best_signal": {"symbol": "BONK", "return_pct": 43.2},
        }
        d.update(kwargs)
        return d

    @pytest.mark.asyncio
    async def test_happy_path_all_sections_present(self):
        bot = _make_bot()
        data = self._full_data()
        ai_insight = "Whales rotated into meme tokens with established communities."

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="123"), \
             patch("services.telegram._build_briefing_data", AsyncMock(return_value=data)), \
             patch("services.gemini.analyse_daily_briefing", AsyncMock(return_value=ai_insight)):
            await send_daily_briefing()

        bot.send_message.assert_awaited_once()
        text = bot.send_message.call_args.kwargs["text"]
        assert "ZENTRYX DAILY BRIEFING" in text
        assert "📊" in text          # stats block
        assert "🔥" in text          # accumulation block
        assert "⚠️" in text          # exits block
        assert "🤖" in text          # AI block
        assert "📈" in text          # best signal block
        assert "zentryx.app/live" not in text

    @pytest.mark.asyncio
    async def test_groq_fails_no_ai_section(self):
        bot = _make_bot()
        data = self._full_data()

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="123"), \
             patch("services.telegram._build_briefing_data", AsyncMock(return_value=data)), \
             patch("services.gemini.analyse_daily_briefing", AsyncMock(return_value=None)):
            await send_daily_briefing()

        text = bot.send_message.call_args.kwargs["text"]
        assert "🤖" not in text       # AI section omitted
        assert "📊" in text           # data still there
        assert "🔥" in text

    @pytest.mark.asyncio
    async def test_zero_trades_quiet_day_fallback(self):
        bot = _make_bot()
        data = self._full_data(total_trades=0, buy_count=0, sell_count=0,
                               total_volume_usd=0, accumulation_tokens=[],
                               exit_tokens=[], best_signal=None)

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="123"), \
             patch("services.telegram._build_briefing_data", AsyncMock(return_value=data)), \
             patch("services.gemini.analyse_daily_briefing", AsyncMock(return_value=None)):
            await send_daily_briefing()

        text = bot.send_message.call_args.kwargs["text"]
        assert "Quiet" in text or "quiet" in text or "No whale" in text

    @pytest.mark.asyncio
    async def test_no_exit_tokens_omits_warning_section(self):
        bot = _make_bot()
        data = self._full_data(sell_count=0, exit_tokens=[])

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="123"), \
             patch("services.telegram._build_briefing_data", AsyncMock(return_value=data)), \
             patch("services.gemini.analyse_daily_briefing", AsyncMock(return_value=None)):
            await send_daily_briefing()

        text = bot.send_message.call_args.kwargs["text"]
        assert "⚠️" not in text

    @pytest.mark.asyncio
    async def test_no_best_signal_omits_best_signal_section(self):
        bot = _make_bot()
        data = self._full_data(best_signal=None)

        with patch("services.telegram._get_bot", return_value=bot), \
             patch("services.telegram._group_chat_id", return_value="123"), \
             patch("services.telegram._build_briefing_data", AsyncMock(return_value=data)), \
             patch("services.gemini.analyse_daily_briefing", AsyncMock(return_value=None)):
            await send_daily_briefing()

        text = bot.send_message.call_args.kwargs["text"]
        assert "📈" not in text

    @pytest.mark.asyncio
    async def test_telegram_not_configured_no_crash(self):
        """When bot/chat_id are not set, must return silently without crashing."""
        with patch("services.telegram._get_bot", return_value=None), \
             patch("services.telegram._group_chat_id", return_value=""):
            await send_daily_briefing()  # must not raise


# ---------------------------------------------------------------------------
# 8-9. analyse_daily_briefing
# ---------------------------------------------------------------------------

class TestAnalyseDailyBriefing:
    @pytest.mark.asyncio
    async def test_returns_string_from_groq(self):
        data = {
            "total_trades": 10, "buy_count": 7, "sell_count": 3,
            "total_volume_usd": 500_000,
            "accumulation_tokens": [{"symbol": "BONK", "wallet_count": 3, "total_usd": 300_000}],
            "exit_tokens": [],
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Whales are accumulating meme tokens."
        mock_client.chat.completions.create.return_value = mock_response

        with patch("services.gemini._get_client", AsyncMock(return_value=mock_client)):
            result = await analyse_daily_briefing(data)

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Whales" in result

    @pytest.mark.asyncio
    async def test_groq_unavailable_returns_none(self):
        data = {"total_trades": 5, "buy_count": 5, "sell_count": 0,
                "total_volume_usd": 100_000, "accumulation_tokens": [], "exit_tokens": []}

        with patch("services.gemini._get_client", AsyncMock(return_value=None)):
            result = await analyse_daily_briefing(data)

        assert result is None


# ---------------------------------------------------------------------------
# 10. Scheduler has daily_briefing job at hour=9
# ---------------------------------------------------------------------------

class TestSchedulerJob:
    def test_daily_briefing_job_registered(self):
        from scheduler import scheduler
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "daily_briefing" in job_ids

    def test_daily_briefing_job_fires_at_9am(self):
        from scheduler import scheduler
        job = next(j for j in scheduler.get_jobs() if j.id == "daily_briefing")
        # APScheduler CronTrigger stores fields; check the hour field
        trigger = job.trigger
        # trigger.fields is a list of CronField objects
        hour_field = next(f for f in trigger.fields if f.name == "hour")
        assert str(hour_field) == "9"
