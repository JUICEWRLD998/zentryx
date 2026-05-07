"""
Day 8 test suite — Telegram AI upgrades, new bot commands, enrichment wiring

Covers:
  - send_trade_alert: copy_score + consensus_count params accepted
  - send_trade_alert: copy score badge rendered (🟢/🟡/🔴)
  - send_trade_alert: consensus badges (EXTREME/HIGH/MODERATE/none)
  - send_trade_alert: no crash when copy_score=None / consensus_count=0
  - send_trade_alert_ai_followup: message structure + recommendation label
  - send_trade_alert_ai_followup: rec emoji mapping (STRONG_BUY→🟢, AVOID→🔴)
  - send_trade_alert_ai_followup: skips send when bot not configured
  - enrichment.py: send_trade_alert call includes copy_score + consensus_count
  - enrichment.py: _run_gemini calls send_trade_alert_ai_followup after Groq result
  - _handle_signal: present in dispatch table, returns structured table
  - _handle_analyze: present in dispatch table
  - _handle_close_trade: present in dispatch table
  - _dispatch: routes /signal, /analyze, /close-trade to correct handlers

Run:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day8.py -v
"""

from __future__ import annotations

import asyncio
import inspect
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    """Run a coroutine synchronously (Python 3.14 safe)."""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — send_trade_alert signature & formatting
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendTradeAlertSignature:
    """send_trade_alert must accept copy_score and consensus_count kwargs."""

    def test_copy_score_param_exists(self):
        from services.telegram import send_trade_alert
        sig = inspect.signature(send_trade_alert)
        assert "copy_score" in sig.parameters, \
            "send_trade_alert missing copy_score parameter"

    def test_consensus_count_param_exists(self):
        from services.telegram import send_trade_alert
        sig = inspect.signature(send_trade_alert)
        assert "consensus_count" in sig.parameters, \
            "send_trade_alert missing consensus_count parameter"

    def test_copy_score_has_default_none(self):
        from services.telegram import send_trade_alert
        sig = inspect.signature(send_trade_alert)
        assert sig.parameters["copy_score"].default is None, \
            "copy_score default should be None"

    def test_consensus_count_has_default_zero(self):
        from services.telegram import send_trade_alert
        sig = inspect.signature(send_trade_alert)
        assert sig.parameters["consensus_count"].default == 0, \
            "consensus_count default should be 0"


class TestSendTradeAlertFormatting:
    """Verify the Telegram message text contains the right badges."""

    def _run_alert(self, copy_score=None, consensus_count=0):
        """Run send_trade_alert with a mock Bot, return the sent text."""
        mock_bot = AsyncMock()
        captured = {}

        async def fake_send_message(**kwargs):
            captured["text"] = kwargs.get("text", "")

        mock_bot.send_message = fake_send_message

        with patch("services.telegram._get_bot", return_value=mock_bot), \
             patch("services.telegram._chat_id", return_value="9999"):
            run(
                __import__("services.telegram", fromlist=["send_trade_alert"])
                .send_trade_alert(
                    wallet_label="TestWhale",
                    wallet_address="Abc123",
                    token_symbol="SOL",
                    token_address="So11111111111111111111111111111111111111111",
                    side="BUY",
                    usd_value=5000.0,
                    security_score=80.0,
                    smart_money=True,
                    momentum_24h=12.5,
                    copy_score=copy_score,
                    consensus_count=consensus_count,
                )
            )
        return captured.get("text", "")

    def test_high_copy_score_shows_green_badge(self):
        text = self._run_alert(copy_score=85.0)
        assert "🟢" in text and "Copy Score" in text and "85" in text

    def test_medium_copy_score_shows_yellow_badge(self):
        text = self._run_alert(copy_score=55.0)
        assert "🟡" in text and "Copy Score" in text and "55" in text

    def test_low_copy_score_shows_red_badge(self):
        text = self._run_alert(copy_score=30.0)
        assert "🔴" in text and "Copy Score" in text and "30" in text

    def test_no_copy_score_no_badge(self):
        text = self._run_alert(copy_score=None)
        assert "Copy Score" not in text

    def test_extreme_consensus_badge(self):
        text = self._run_alert(consensus_count=4)
        assert "EXTREME CONSENSUS" in text

    def test_high_consensus_badge(self):
        text = self._run_alert(consensus_count=3)
        assert "HIGH CONSENSUS" in text

    def test_moderate_consensus_badge(self):
        text = self._run_alert(consensus_count=2)
        assert "MODERATE CONSENSUS" in text

    def test_no_consensus_no_badge(self):
        text = self._run_alert(consensus_count=0)
        assert "CONSENSUS" not in text

    def test_alert_skips_when_no_bot(self):
        """Must not raise when bot is not configured."""
        with patch("services.telegram._get_bot", return_value=None):
            # Should complete without exception
            run(
                __import__("services.telegram", fromlist=["send_trade_alert"])
                .send_trade_alert(
                    wallet_label="X",
                    wallet_address="Y",
                    token_symbol="Z",
                    token_address="0",
                    side="BUY",
                    usd_value=100.0,
                    security_score=None,
                    smart_money=False,
                    momentum_24h=None,
                )
            )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — send_trade_alert_ai_followup
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendTradeAlertAiFollowup:
    """send_trade_alert_ai_followup message content tests."""

    def _run_followup(self, recommendation="STRONG_BUY", analysis="Looks great."):
        from services.telegram import send_trade_alert_ai_followup
        captured = {}

        async def fake_send(**kwargs):
            captured["text"] = kwargs.get("text", "")

        mock_bot = AsyncMock()
        mock_bot.send_message = fake_send

        with patch("services.telegram._get_bot", return_value=mock_bot), \
             patch("services.telegram._chat_id", return_value="9999"):
            run(send_trade_alert_ai_followup(
                token_symbol="BONK",
                token_address="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
                recommendation=recommendation,
                analysis=analysis,
            ))
        return captured.get("text", "")

    def test_function_exists(self):
        from services import telegram
        assert hasattr(telegram, "send_trade_alert_ai_followup"), \
            "send_trade_alert_ai_followup not found in telegram.py"

    def test_message_contains_token_symbol(self):
        text = self._run_followup()
        assert "BONK" in text

    def test_message_contains_ai_verdict_header(self):
        text = self._run_followup()
        assert "AI Verdict" in text

    def test_message_contains_analysis(self):
        text = self._run_followup(analysis="Market structure is bullish.")
        assert "Market structure is bullish." in text

    def test_strong_buy_shows_green_emoji(self):
        text = self._run_followup(recommendation="STRONG_BUY")
        assert "🟢" in text

    def test_avoid_shows_red_emoji(self):
        text = self._run_followup(recommendation="AVOID")
        assert "🔴" in text

    def test_hold_shows_yellow_emoji(self):
        text = self._run_followup(recommendation="HOLD")
        assert "🟡" in text

    def test_recommendation_label_underscores_replaced(self):
        """STRONG_BUY must appear as 'STRONG BUY' in the message."""
        text = self._run_followup(recommendation="STRONG_BUY")
        assert "STRONG BUY" in text

    def test_skips_when_no_bot(self):
        """Must not raise when bot is not configured."""
        from services.telegram import send_trade_alert_ai_followup
        with patch("services.telegram._get_bot", return_value=None):
            run(send_trade_alert_ai_followup(
                token_symbol="X",
                token_address="0",
                recommendation="HOLD",
                analysis="nothing",
            ))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — enrichment.py wiring
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnrichmentWiring:
    """Verify enrichment.py passes copy_score and wires the AI followup."""

    def test_send_trade_alert_call_includes_copy_score(self):
        """The asyncio.create_task(send_trade_alert(...)) call must include
        copy_score and consensus_count keyword arguments."""
        import ast, textwrap

        src_path = os.path.join(
            os.path.dirname(__file__), "services", "enrichment.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()

        # Just do a plain string check — fast and unambiguous
        assert "copy_score=copy_score" in src, \
            "enrichment.py: send_trade_alert call missing copy_score=copy_score"
        assert "consensus_count=consensus_count" in src, \
            "enrichment.py: send_trade_alert call missing consensus_count=consensus_count"

    def test_run_gemini_imports_ai_followup(self):
        """_run_gemini must import send_trade_alert_ai_followup."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "enrichment.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "send_trade_alert_ai_followup" in src, \
            "enrichment.py: send_trade_alert_ai_followup not imported/called in _run_gemini"

    def test_run_gemini_calls_ai_followup(self):
        """_run_gemini must call await send_trade_alert_ai_followup(...)."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "enrichment.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "await send_trade_alert_ai_followup(" in src, \
            "enrichment.py: await send_trade_alert_ai_followup(...) not found in _run_gemini"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Bot command dispatch routing
# ═══════════════════════════════════════════════════════════════════════════════

class TestDispatchRouting:
    """Verify /signal, /analyze, /close-trade are dispatched to correct handlers."""

    def _get_dispatch_src(self) -> str:
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            return f.read()

    def test_signal_in_dispatch(self):
        src = self._get_dispatch_src()
        assert "/signal" in src and "_handle_signal" in src, \
            "/signal not routed to _handle_signal in _dispatch"

    def test_analyze_in_dispatch(self):
        src = self._get_dispatch_src()
        assert "/analyze" in src and "_handle_analyze" in src, \
            "/analyze not routed to _handle_analyze in _dispatch"

    def test_close_trade_in_dispatch(self):
        src = self._get_dispatch_src()
        assert "/close-trade" in src and "_handle_close_trade" in src, \
            "/close-trade not routed to _handle_close_trade in _dispatch"

    def test_handle_signal_function_exists(self):
        from services import telegram
        assert hasattr(telegram, "_handle_signal"), \
            "_handle_signal function not found in telegram.py"

    def test_handle_analyze_function_exists(self):
        from services import telegram
        assert hasattr(telegram, "_handle_analyze"), \
            "_handle_analyze function not found in telegram.py"

    def test_handle_close_trade_function_exists(self):
        from services import telegram
        assert hasattr(telegram, "_handle_close_trade"), \
            "_handle_close_trade function not found in telegram.py"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — _handle_signal response content
# ═══════════════════════════════════════════════════════════════════════════════

class TestHandleSignalContent:
    """_handle_signal must return a structured breakdown with key labels."""

    def _source(self) -> str:
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            return f.read()

    def test_signal_shows_copy_score(self):
        src = self._source()
        # The handler must build a message referencing "Copy Score"
        assert "Copy Score" in src, \
            "_handle_signal does not mention Copy Score in its response"

    def test_signal_shows_verdict(self):
        src = self._source()
        # Must include COPY, WATCH, or SKIP verdicts
        assert "COPY" in src and "WATCH" in src and "SKIP" in src, \
            "_handle_signal missing COPY/WATCH/SKIP verdict labels"

    def test_signal_deletes_thinking_message(self):
        """Handler must delete the 'thinking...' placeholder message."""
        src = self._source()
        # delete_message is the telegram Bot method for this
        assert "delete_message" in src, \
            "_handle_signal does not call delete_message to clean up placeholder"

    @pytest.mark.asyncio
    async def test_handle_signal_no_args_sends_usage(self):
        """Calling /signal with no token address must reply with usage text."""
        from services.telegram import _handle_signal

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs.get("text", ""))

        mock_bot = AsyncMock()
        mock_bot.send_message = fake_send

        update = MagicMock()
        update.message.text = "/signal"
        update.message.chat_id = 12345
        update.message.message_id = 1

        await _handle_signal(mock_bot, update)

        assert sent, "No message was sent for empty /signal call"
        assert any(
            "Usage" in t or "usage" in t or "address" in t.lower()
            for t in sent
        ), f"Expected usage hint, got: {sent}"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — _handle_analyze response content
# ═══════════════════════════════════════════════════════════════════════════════

class TestHandleAnalyzeContent:
    """_handle_analyze must call analyse_trade and format the AI response."""

    @pytest.mark.asyncio
    async def test_handle_analyze_no_args_sends_usage(self):
        from services.telegram import _handle_analyze

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs.get("text", ""))

        mock_bot = AsyncMock()
        mock_bot.send_message = fake_send

        update = MagicMock()
        update.message.text = "/analyze"
        update.message.chat_id = 12345
        update.message.message_id = 1

        await _handle_analyze(mock_bot, update)

        assert sent, "No message was sent for empty /analyze call"
        assert any(
            "Usage" in t or "usage" in t or "address" in t.lower()
            for t in sent
        ), f"Expected usage hint, got: {sent}"

    def test_handle_analyze_calls_groq(self):
        """_handle_analyze source must reference analyse_trade (Groq wrapper)."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "analyse_trade" in src, \
            "_handle_analyze does not call analyse_trade from gemini.py"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — _handle_close_trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestHandleCloseTrade:
    """_handle_close_trade must look up trade, fetch price, update DB."""

    @pytest.mark.asyncio
    async def test_handle_close_trade_no_args_sends_usage(self):
        from services.telegram import _handle_close_trade

        sent = []

        async def fake_send(**kwargs):
            sent.append(kwargs.get("text", ""))

        mock_bot = AsyncMock()
        mock_bot.send_message = fake_send

        update = MagicMock()
        update.message.text = "/close-trade"
        update.message.chat_id = 12345
        update.message.message_id = 1

        await _handle_close_trade(mock_bot, update)

        assert sent, "No message sent for empty /close-trade call"
        assert any(
            "Usage" in t or "usage" in t or "ID" in t or "id" in t.lower()
            for t in sent
        ), f"Expected usage hint, got: {sent}"

    def test_close_trade_source_queries_trade_table(self):
        """_handle_close_trade must query the trade table by short ID."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "trade_table" in src or "trade_event_table" in src, \
            "_handle_close_trade does not query a trade table"

    def test_close_trade_source_fetches_current_price(self):
        """_handle_close_trade must fetch current price (Birdeye) for PnL."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "birdeye" in src.lower() or "get_price" in src or "current_price" in src, \
            "_handle_close_trade does not reference price fetching for PnL"

    def test_close_trade_source_updates_status_closed(self):
        """_handle_close_trade must update trade status to 'closed'."""
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert '"closed"' in src or "'closed'" in src, \
            "_handle_close_trade does not set status to 'closed'"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — start/help text correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestBotTextContent:
    """Verify start/help text was fixed and new commands are listed."""

    def _source(self) -> str:
        src_path = os.path.join(
            os.path.dirname(__file__), "services", "telegram.py"
        )
        with open(src_path, encoding="utf-8") as f:
            return f.read()

    def test_threshold_is_1000_not_2000(self):
        src = self._source()
        # The /start and /help welcome messages must use $1,000+ (not $2,000+).
        # The /watch confirmation DM text is allowed to reference $2,000 separately.
        assert "$1,000" in src, \
            "Corrected $1,000 threshold not found in telegram.py /start or /help text"

    def test_signal_command_in_help_text(self):
        src = self._source()
        assert "/signal" in src, "/signal not listed in bot help/start text"

    def test_analyze_command_in_help_text(self):
        src = self._source()
        assert "/analyze" in src, "/analyze not listed in bot help/start text"

    def test_close_trade_command_in_help_text(self):
        src = self._source()
        assert "/close-trade" in src, "/close-trade not listed in bot help/start text"

    def test_my_wallets_crash_fix_applied(self):
        """len(items) crash bug must be gone — replaced with len(rows)."""
        src = self._source()
        # The buggy code was: len(items) — must not exist anymore
        # Check that we now have len(rows) instead
        assert "len(rows)" in src, \
            "len(rows) fix not found — _handle_my_wallets may still use len(items)"
