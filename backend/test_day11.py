"""
Day 11 functional tests — Stream D: signal_outcome persistence + /stats wiring.

Tests:
  Group A — signal_outcome upsert in calculate_signal_profitability
    A1. Happy path: upsert executed after successful compute
    A2. DB unavailable: upsert skipped, no exception
    A3. Upsert failure swallowed: _cache still populated

  Group B — /stats command signal accuracy line
    B1. Cache valid, total_signals > 0 → message contains "Signal Accuracy"
    B2. Cache is None → message sent, no "Signal Accuracy", no crash
    B3. Cache has total_signals == 0 → accuracy section omitted
    B4. Existing /stats fields unaffected (regression)

  Group C — structural / regression
    C1. signal_outcome_table exists in db.metadata.tables
    C2. signal_outcome_table has all 8 expected columns
    C3. get_cached_stats() returns None before first compute call

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day11.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade_row(address="tokenA", symbol="BONK", usd=0.05, ts=None):
    from datetime import datetime, timezone, timedelta
    row = MagicMock()
    row.token_address = address
    row.token_symbol = symbol
    row.usd_value = usd
    row.side = "BUY"
    row.smart_money_flag = True
    row.timestamp = ts or (datetime.now(tz=timezone.utc) - timedelta(hours=6))
    return row


def _make_wallet(label="Whale A", pnl=50_000.0, win_rate=0.72, trade_count=120):
    w = MagicMock()
    w.label = label
    w.total_pnl = pnl
    w.win_rate = win_rate
    w.trade_count = trade_count
    return w


def _make_session_ctx(execute_results=None, execute_side_effect=None):
    """Return a context-manager mock for get_session()."""
    session = AsyncMock()
    if execute_side_effect is not None:
        session.execute = AsyncMock(side_effect=execute_side_effect)
    elif execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        result = MagicMock()
        result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# ---------------------------------------------------------------------------
# Group A — signal_outcome upsert
# ---------------------------------------------------------------------------

class TestSignalOutcomeUpsert:

    @pytest.mark.asyncio
    async def test_a1_upsert_executed_on_happy_path(self):
        """After a successful compute, session.execute is called twice:
        once for the SELECT and once for the upsert INSERT."""
        from datetime import datetime, timezone, timedelta
        row = _make_trade_row(address="tokenA", symbol="BONK", usd=0.05)

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        # Two separate session contexts (one per `async with get_session()` block)
        select_session = AsyncMock()
        select_session.execute = AsyncMock(return_value=select_result)
        select_ctx = MagicMock()
        select_ctx.__aenter__ = AsyncMock(return_value=select_session)
        select_ctx.__aexit__ = AsyncMock(return_value=False)

        upsert_session = AsyncMock()
        upsert_ctx = MagicMock()
        upsert_ctx.__aenter__ = AsyncMock(return_value=upsert_session)
        upsert_ctx.__aexit__ = AsyncMock(return_value=False)

        session_factory = MagicMock(side_effect=[select_ctx, upsert_ctx])

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", side_effect=lambda: session_factory()), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value={
                 "data": {"value": 0.08}
             })):
            import services.signal_stats as ss
            ss._cache = None
            await ss.calculate_signal_profitability()

        # _cache must be populated
        assert ss._cache is not None
        assert ss._cache["total_signals"] == 1

        # Upsert session.execute must have been called (the INSERT ... ON CONFLICT)
        assert upsert_session.execute.called, "Upsert execute was not called"

    @pytest.mark.asyncio
    async def test_a2_upsert_skipped_when_db_unavailable(self):
        """When DB is unavailable, calculate_signal_profitability returns early
        without touching the session at all."""
        with patch("db.is_available", return_value=False), \
             patch("db.get_session") as mock_get_session:
            import services.signal_stats as ss
            ss._cache = None
            await ss.calculate_signal_profitability()

        mock_get_session.assert_not_called()
        # _cache stays None (early return)
        assert ss._cache is None

    @pytest.mark.asyncio
    async def test_a3_upsert_failure_swallowed_cache_still_set(self):
        """If the upsert session.execute raises, the exception is caught and
        _cache is still populated from the earlier assignment."""
        row = _make_trade_row(address="tokenA", symbol="BONK", usd=0.05)

        select_result = MagicMock()
        select_result.fetchall.return_value = [row]

        select_session = AsyncMock()
        select_session.execute = AsyncMock(return_value=select_result)
        select_ctx = MagicMock()
        select_ctx.__aenter__ = AsyncMock(return_value=select_session)
        select_ctx.__aexit__ = AsyncMock(return_value=False)

        # Upsert session raises
        failing_session = AsyncMock()
        failing_session.execute = AsyncMock(side_effect=RuntimeError("DB timeout"))
        fail_ctx = MagicMock()
        fail_ctx.__aenter__ = AsyncMock(return_value=failing_session)
        fail_ctx.__aexit__ = AsyncMock(return_value=False)

        session_factory = MagicMock(side_effect=[select_ctx, fail_ctx])

        with patch("db.is_available", return_value=True), \
             patch("db.get_session", side_effect=lambda: session_factory()), \
             patch("services.birdeye.get_token_price", new=AsyncMock(return_value={
                 "data": {"value": 0.08}
             })):
            import services.signal_stats as ss
            ss._cache = None
            await ss.calculate_signal_profitability()  # must not raise

        # Cache must still be set despite the upsert failure
        assert ss._cache is not None
        assert ss._cache["total_signals"] == 1


# ---------------------------------------------------------------------------
# Group B — /stats command
# ---------------------------------------------------------------------------

class TestStatsCommand:

    def _make_update(self, chat_id=42):
        update = MagicMock()
        update.message.chat.id = chat_id
        update.message.text = "/stats"
        return update

    def _make_bot(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    def _stats_cache(self, total=50, profitable=36, win_rate=71.4, avg_return=18.3):
        return {
            "computed_at": "2026-05-07T09:00:00+00:00",
            "total_signals": total,
            "profitable": profitable,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "top_performers": [],
        }

    @pytest.mark.asyncio
    async def test_b1_signal_accuracy_shown_when_cache_valid(self):
        """When stats cache has total_signals > 0, message contains accuracy block."""
        from services.telegram import _handle_stats
        wallets = [_make_wallet()]
        bot = self._make_bot()
        update = self._make_update()

        with patch("services.wallet_discovery.get_tracked_wallets", return_value=wallets), \
             patch("services.signal_stats.get_cached_stats", return_value=self._stats_cache()):
            await _handle_stats(bot, update)

        sent_text = bot.send_message.call_args.kwargs["text"]
        assert "Signal Accuracy" in sent_text
        assert "71.4%" in sent_text
        assert "+18.3%" in sent_text
        assert "50 signals" in sent_text

    @pytest.mark.asyncio
    async def test_b2_no_accuracy_when_cache_none(self):
        """When cache is None (not yet computed), accuracy block is omitted, no crash."""
        from services.telegram import _handle_stats
        wallets = [_make_wallet()]
        bot = self._make_bot()
        update = self._make_update()

        with patch("services.wallet_discovery.get_tracked_wallets", return_value=wallets), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            await _handle_stats(bot, update)

        assert bot.send_message.called
        sent_text = bot.send_message.call_args.kwargs["text"]
        assert "Signal Accuracy" not in sent_text

    @pytest.mark.asyncio
    async def test_b3_no_accuracy_when_total_signals_zero(self):
        """Cache with total_signals == 0 → accuracy section omitted."""
        from services.telegram import _handle_stats
        wallets = [_make_wallet()]
        bot = self._make_bot()
        update = self._make_update()
        zero_cache = self._stats_cache(total=0, profitable=0, win_rate=0.0, avg_return=0.0)

        with patch("services.wallet_discovery.get_tracked_wallets", return_value=wallets), \
             patch("services.signal_stats.get_cached_stats", return_value=zero_cache):
            await _handle_stats(bot, update)

        sent_text = bot.send_message.call_args.kwargs["text"]
        assert "Signal Accuracy" not in sent_text

    @pytest.mark.asyncio
    async def test_b4_existing_fields_unaffected(self):
        """Existing /stats fields still present regardless of signal cache."""
        from services.telegram import _handle_stats
        wallets = [
            _make_wallet(label="Alpha Whale", pnl=100_000.0, win_rate=0.80),
            _make_wallet(label="Beta Whale",  pnl=20_000.0,  win_rate=0.55),
        ]
        bot = self._make_bot()
        update = self._make_update()

        with patch("services.wallet_discovery.get_tracked_wallets", return_value=wallets), \
             patch("services.signal_stats.get_cached_stats", return_value=None):
            await _handle_stats(bot, update)

        sent_text = bot.send_message.call_args.kwargs["text"]
        assert "Wallets tracked" in sent_text or "wallets" in sent_text.lower()
        assert "Zentryx Dashboard Stats" in sent_text
        assert "Alpha Whale" in sent_text   # best performer
        assert "2" in sent_text             # wallet count


# ---------------------------------------------------------------------------
# Group C — structural regression
# ---------------------------------------------------------------------------

class TestStructuralRegression:

    def test_c1_signal_outcome_table_in_metadata(self):
        import db
        assert "signal_outcome" in db.metadata.tables, \
            "signal_outcome_table not registered in db.metadata"

    def test_c2_signal_outcome_table_has_correct_columns(self):
        import db
        table = db.metadata.tables["signal_outcome"]
        expected = {"id", "token_address", "symbol", "entry_usd",
                    "entry_time", "check_time", "current_price", "return_pct"}
        actual = set(table.c.keys())
        missing = expected - actual
        assert not missing, f"Missing columns in signal_outcome: {missing}"

    def test_c3_get_cached_stats_returns_none_before_compute(self):
        import services.signal_stats as ss
        # Reset cache to simulate fresh start
        original = ss._cache
        ss._cache = None
        try:
            result = ss.get_cached_stats()
            assert result is None
        finally:
            ss._cache = original
