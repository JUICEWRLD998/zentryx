"""
Day 9 functional tests — /signal and /analyze handlers + get_live_consensus.

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day9.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.schemas import TokenMiniReport
from services.enrichment import (
    _consensus_tracker,
    _CONSENSUS_WINDOW_S,
    _compute_copy_score,
    get_live_consensus,
)
from services.telegram import _handle_signal, _handle_analyze


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_update(text: str, chat_id: int = 123) -> MagicMock:
    update = MagicMock()
    update.message.chat.id = chat_id
    update.message.text = text
    return update


def make_bot() -> AsyncMock:
    """Return a bot mock whose send_message returns a message with .message_id."""
    bot = AsyncMock()
    thinking_msg = MagicMock()
    thinking_msg.message_id = 999
    bot.send_message.return_value = thinking_msg
    return bot


def make_report(**kwargs) -> TokenMiniReport:
    defaults = dict(
        token_address="TestAddr1234567890",
        symbol="TEST",
        security_score=80.0,
        is_honeypot=False,
        smart_money_flag=False,
        momentum_24h=10.0,
        buy_sell_ratio=0.6,
        total_liquidity_usd=1_000_000.0,
        holder_count=500,
        market_cap=5_000_000.0,
        volume_24h=100_000.0,
        consensus_count=0,
    )
    defaults.update(kwargs)
    return TokenMiniReport(**defaults)


# ---------------------------------------------------------------------------
# 1-2.  get_live_consensus — unit tests
# ---------------------------------------------------------------------------

class TestGetLiveConsensus:
    def setup_method(self):
        # Clear tracker state for the test token before each test
        _consensus_tracker.pop("TOKEN_A", None)

    def test_returns_zero_when_no_entries(self):
        assert get_live_consensus("TOKEN_A") == 0

    def test_returns_correct_count(self):
        now = time.monotonic()
        _consensus_tracker["TOKEN_A"] = [
            ("wallet1", now),
            ("wallet2", now),
            ("wallet3", now),
        ]
        assert get_live_consensus("TOKEN_A") == 3

    def test_prunes_stale_entries(self):
        now = time.monotonic()
        stale_ts = now - _CONSENSUS_WINDOW_S - 1  # 1 second past the window
        fresh_ts = now - 10  # 10s ago → within window
        _consensus_tracker["TOKEN_A"] = [
            ("wallet_stale", stale_ts),
            ("wallet_fresh", fresh_ts),
        ]
        assert get_live_consensus("TOKEN_A") == 1  # only wallet_fresh survives

    def test_does_not_add_new_entries(self):
        """get_live_consensus must be read-only — no side effects."""
        now = time.monotonic()
        _consensus_tracker["TOKEN_A"] = [("wallet1", now)]
        before = list(_consensus_tracker["TOKEN_A"])
        get_live_consensus("TOKEN_A")
        after = list(_consensus_tracker["TOKEN_A"])
        assert after == before


# ---------------------------------------------------------------------------
# 3-10. /signal handler — functional tests
# ---------------------------------------------------------------------------

class TestHandleSignal:
    """All tests mock build_mini_report and get_live_consensus in the enrichment module."""

    @pytest.mark.asyncio
    async def test_happy_path_message_structure(self):
        """Message must contain all 6 factor labels and Copy Score."""
        report = make_report()
        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        sent_calls = bot.send_message.call_args_list
        # Second call is the actual report (first is thinking message)
        report_text = sent_calls[1].kwargs.get("text", "") or sent_calls[1].args[0] if len(sent_calls[1].args) > 0 else ""
        # Prefer kwargs
        texts = [call.kwargs.get("text", "") for call in sent_calls]
        full_text = " ".join(texts)

        assert "Copy Score" in full_text
        assert "Factor Breakdown" in full_text
        assert "Security" in full_text
        assert "Smart Money" in full_text
        assert "Momentum" in full_text
        assert "Buy/Sell Ratio" in full_text
        assert "Liquidity" in full_text
        assert "Consensus" in full_text

    @pytest.mark.asyncio
    async def test_copy_verdict(self):
        """High-quality data → score ≥ 70 → COPY verdict."""
        report = make_report(
            security_score=95.0,
            smart_money_flag=True,
            momentum_24h=35.0,
            buy_sell_ratio=0.75,
            total_liquidity_usd=4_000_000.0,
        )
        # Verify expected score ourselves
        expected_score = _compute_copy_score(report, 0)
        assert expected_score >= 70, f"Test setup error: score {expected_score} not ≥ 70"

        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "COPY" in full_text
        assert "🟢" in full_text

    @pytest.mark.asyncio
    async def test_skip_verdict(self):
        """Low-quality data → score < 50 → SKIP verdict."""
        report = make_report(
            security_score=20.0,
            smart_money_flag=False,
            momentum_24h=-15.0,
            buy_sell_ratio=0.32,
            total_liquidity_usd=50_000.0,
        )
        expected_score = _compute_copy_score(report, 0)
        assert expected_score < 50, f"Test setup error: score {expected_score} not < 50"

        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "SKIP" in full_text
        assert "🔴" in full_text

    @pytest.mark.asyncio
    async def test_consensus_badge_shown_when_3_whales(self):
        """Consensus badge appears when get_live_consensus returns 3."""
        report = make_report()
        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=3):
            await _handle_signal(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "3 whale" in full_text
        assert "whales bought this token" in full_text.lower() or "whales bought this token" in full_text

    @pytest.mark.asyncio
    async def test_consensus_badge_not_shown_when_1_whale(self):
        """No badge when only 1 whale (threshold is 2+)."""
        report = make_report()
        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=1):
            await _handle_signal(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "whales bought this token" not in full_text

    @pytest.mark.asyncio
    async def test_thinking_message_deleted(self):
        """Thinking message is always deleted in finally."""
        report = make_report()
        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        bot.delete_message.assert_awaited_once()
        call_kwargs = bot.delete_message.call_args.kwargs
        assert call_kwargs.get("message_id") == 999

    @pytest.mark.asyncio
    async def test_thinking_message_deleted_on_exception(self):
        """Thinking message is deleted even when enrichment raises."""
        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(side_effect=RuntimeError("API down"))), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        # Error message was sent
        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "❌" in full_text

        # Thinking message still deleted
        bot.delete_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_args_returns_usage_hint(self):
        """/signal with no address → usage text, no enrichment call."""
        bot = make_bot()
        update = make_update("/signal")

        mock_bmr = AsyncMock()
        with patch("services.enrichment.build_mini_report", mock_bmr), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        mock_bmr.assert_not_awaited()
        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "Usage" in full_text or "usage" in full_text

    @pytest.mark.asyncio
    async def test_copy_score_value_in_message(self):
        """The numeric copy score computed from the mock report appears in the message."""
        report = make_report(
            security_score=95.0,
            smart_money_flag=True,
            momentum_24h=35.0,
            buy_sell_ratio=0.75,
            total_liquidity_usd=4_000_000.0,
        )
        expected_score = _compute_copy_score(report, 0)

        bot = make_bot()
        update = make_update("/signal TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_signal(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert f"{expected_score:.0f}/100" in full_text


# ---------------------------------------------------------------------------
# 11-14. /analyze handler — functional tests
# ---------------------------------------------------------------------------

class TestHandleAnalyze:
    @pytest.mark.asyncio
    async def test_happy_path_ai_content_in_message(self):
        """With valid Groq response → AI verdict header, rec label, analysis text."""
        report = make_report(
            security_score=85.0,
            smart_money_flag=True,
            momentum_24h=20.0,
        )
        ai_result = {"recommendation": "STRONG_BUY", "analysis": "Smart money consensus supports entry."}

        bot = make_bot()
        update = make_update("/analyze TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0), \
             patch("services.gemini.analyse_trade", AsyncMock(return_value=ai_result)):
            await _handle_analyze(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "AI Analysis" in full_text
        assert "STRONG BUY" in full_text
        assert "Smart money consensus supports entry." in full_text
        assert "🟢" in full_text
        assert "Copy Score" in full_text

    @pytest.mark.asyncio
    async def test_groq_unavailable_fallback(self):
        """When analyse_trade returns None → fallback message with 'unavailable' and /signal ref."""
        report = make_report()
        bot = make_bot()
        update = make_update("/analyze TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0), \
             patch("services.gemini.analyse_trade", AsyncMock(return_value=None)):
            await _handle_analyze(bot, update)

        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "unavailable" in full_text.lower()
        assert "/signal" in full_text

    @pytest.mark.asyncio
    async def test_thinking_message_deleted(self):
        """Thinking message is always deleted in finally."""
        report = make_report()
        ai_result = {"recommendation": "HOLD", "analysis": "Mixed signals."}
        bot = make_bot()
        update = make_update("/analyze TestAddr1234567890")

        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=0), \
             patch("services.gemini.analyse_trade", AsyncMock(return_value=ai_result)):
            await _handle_analyze(bot, update)

        bot.delete_message.assert_awaited_once()
        call_kwargs = bot.delete_message.call_args.kwargs
        assert call_kwargs.get("message_id") == 999

    @pytest.mark.asyncio
    async def test_no_args_returns_usage_hint(self):
        """/analyze with no address → usage text, no enrichment call."""
        bot = make_bot()
        update = make_update("/analyze")

        mock_bmr = AsyncMock()
        with patch("services.enrichment.build_mini_report", mock_bmr), \
             patch("services.enrichment.get_live_consensus", return_value=0):
            await _handle_analyze(bot, update)

        mock_bmr.assert_not_awaited()
        texts = [call.kwargs.get("text", "") for call in bot.send_message.call_args_list]
        full_text = " ".join(texts)
        assert "Usage" in full_text or "usage" in full_text

    @pytest.mark.asyncio
    async def test_consensus_passed_to_analyse_trade(self):
        """get_live_consensus value is forwarded to analyse_trade as consensus_count."""
        report = make_report()
        ai_result = {"recommendation": "BUY", "analysis": "Consensus trade."}
        bot = make_bot()
        update = make_update("/analyze TestAddr1234567890")

        mock_analyse = AsyncMock(return_value=ai_result)
        with patch("services.enrichment.build_mini_report", AsyncMock(return_value=report)), \
             patch("services.enrichment.get_live_consensus", return_value=4), \
             patch("services.gemini.analyse_trade", mock_analyse):
            await _handle_analyze(bot, update)

        call_kwargs = mock_analyse.call_args.kwargs
        assert call_kwargs.get("consensus_count") == 4
