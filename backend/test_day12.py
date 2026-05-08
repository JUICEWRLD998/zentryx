"""
Day 12 regression tests — daily wallet discovery + WS resubscribe.

Tests:
  1. Scheduler registers daily wallet discovery at 00:00 UTC.
  2. Wallet discovery requests Solana WS resubscribe when tracked addresses change.
  3. Wallet discovery does not request Solana WS resubscribe when tracked addresses stay the same.
  4. Solana RPC WS loop reconnects immediately after a resubscribe request.

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day12.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_gainers(addresses):
    return {
        "data": {
            "items": [{"address": address, "pnl": 1000.0} for address in addresses]
        }
    }


def _make_summary(total_pnl=1000.0, win_rate=0.75, trade_count=12):
    return {
        "pnl": {"realized_profit_usd": total_pnl},
        "counts": {"win_rate": win_rate, "total_trade": trade_count},
    }


class TestDailyDiscoverySchedule:

    def test_daily_wallet_discovery_job_registered(self):
        from scheduler import scheduler

        job = scheduler.get_job("daily_wallet_discovery")
        assert job is not None, "daily_wallet_discovery job not registered"
        assert str(job.trigger) == "cron[hour='0', minute='0']"


class TestWalletDiscoveryResubscribe:

    @pytest.mark.asyncio
    async def test_resubscribe_requested_when_tracked_wallet_set_changes(self):
        import services.wallet_discovery as wd

        wd.tracked_wallets = {
            "old-wallet": MagicMock(),
        }

        with patch("services.wallet_discovery.birdeye.get_gainers_losers", new=AsyncMock(return_value=_make_gainers(["new-wallet-a", "new-wallet-b"]))), \
             patch("services.wallet_discovery._fetch_pnl_batch", new=AsyncMock(return_value=[
                 ("new-wallet-a", _make_summary(total_pnl=3000.0)),
                 ("new-wallet-b", _make_summary(total_pnl=2000.0)),
             ])), \
             patch("services.wallet_discovery.db.is_available", return_value=False), \
             patch("services.solana_rpc_ws.request_resubscribe") as mock_request:
            await wd.discover_wallets()

        assert set(wd.tracked_wallets.keys()) == {"new-wallet-a", "new-wallet-b"}
        mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_resubscribe_not_requested_when_tracked_wallet_set_unchanged(self):
        import services.wallet_discovery as wd

        wd.tracked_wallets = {
            "wallet-a": MagicMock(),
            "wallet-b": MagicMock(),
        }

        with patch("services.wallet_discovery.birdeye.get_gainers_losers", new=AsyncMock(return_value=_make_gainers(["wallet-a", "wallet-b"]))), \
             patch("services.wallet_discovery._fetch_pnl_batch", new=AsyncMock(return_value=[
                 ("wallet-a", _make_summary(total_pnl=4000.0)),
                 ("wallet-b", _make_summary(total_pnl=1000.0)),
             ])), \
             patch("services.wallet_discovery.db.is_available", return_value=False), \
             patch("services.solana_rpc_ws.request_resubscribe") as mock_request:
            await wd.discover_wallets()

        assert set(wd.tracked_wallets.keys()) == {"wallet-a", "wallet-b"}
        mock_request.assert_not_called()


class TestSolanaWsReconnect:

    @pytest.mark.asyncio
    async def test_run_loop_reconnects_immediately_after_resubscribe_request(self):
        import services.solana_rpc_ws as rpc_ws

        call_count = 0

        async def fake_run_connection(_on_event):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rpc_ws.ResubscribeRequested()
            raise asyncio.CancelledError()

        with patch("services.solana_rpc_ws._run_connection", new=AsyncMock(side_effect=fake_run_connection)), \
             patch("services.solana_rpc_ws.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await rpc_ws.run_solana_rpc_ws(AsyncMock())

        assert call_count == 2, "WS loop did not reconnect immediately after resubscribe"
        assert mock_sleep.await_count == 0, "WS loop slept instead of reconnecting immediately"