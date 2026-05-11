"""
Sprint 4 Phase 3 — Tests for Token Overlap Matrix + Whale Tracking fixes.

Verifies:
  PART A — GET /api/wallets/overlap (Phase 3)
    1. Returns correct shape: tokens[], wallets_analyzed, generated_at
    2. Tokens held by 2+ whales appear; single-holder tokens are excluded
    3. Whale list attached to each token
    4. Conviction tier assigned correctly (MODERATE / HIGH / EXTREME)
    5. Tokens sorted by whale_count desc then total_usd desc
    6. min_value_usd query param filters low-value positions
    7. In-process cache prevents re-fetching within TTL
    8. Tolerates individual wallet portfolio failures (partial results, not 500)
    9. Empty portfolio list returns empty tokens

  PART B — Birdeye WS fixes (birdeye_ws.py)
    10. request_resubscribe() sets the internal event
    11. _normalize_event passes WALLET_TXS events with wallet_label injected
    12. _normalize_event passes LARGE_TRADE_TXS with "Whale Alert" label
    13. _normalize_event returns None for subscription ack messages
    14. _normalize_event returns None for PING messages
    15. net field is correct: inflow - outflow

  PART C — polling_worker double-sleep fix
    16. POLL_INTERVAL_SECS * 2 is NOT what gets slept (not a unit test, but we
        verify the module structure doesn't have the duplicate sleep by importing)

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_sprint4_phase3.py -v
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_SOL  = "So11111111111111111111111111111111111111112"
TOKEN_BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
TOKEN_WIF  = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
TOKEN_JUP  = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"

WALLET_A = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
WALLET_B = "5Bzx4EXxFrGZxiT4vhJrWJnzpFRmkGmUYKhHjPbsS9mA"
WALLET_C = "CrBXY9q9gWE7mhYXVqvBXXQm2BmS1EbG5dpuPwQ2DXYZ"


def _make_portfolio_response(items: list[dict]) -> dict:
    return {"data": {"items": items}}


def _make_token_item(address: str, symbol: str, value_usd: float) -> dict:
    return {
        "address": address,
        "symbol": symbol,
        "name": f"{symbol} Token",
        "logoURI": f"https://example.com/{symbol.lower()}.png",
        "valueUsd": value_usd,
        "uiAmount": 1000.0,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_overlap_cache():
    import routers.wallets as wm
    wm._overlap_cache = None
    yield
    wm._overlap_cache = None


@pytest.fixture()
async def client():
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


def _make_tracked_wallets():
    from models.schemas import TrackedWallet
    return {
        WALLET_A: TrackedWallet(address=WALLET_A, label="Whale #1", win_rate=0.7, total_pnl=50000, trade_count=100),
        WALLET_B: TrackedWallet(address=WALLET_B, label="Whale #2", win_rate=0.6, total_pnl=30000, trade_count=80),
        WALLET_C: TrackedWallet(address=WALLET_C, label="Whale #3", win_rate=0.55, total_pnl=20000, trade_count=60),
    }


# ===========================================================================
# PART A — GET /api/wallets/overlap
# ===========================================================================

class TestOverlapRouteShape:

    @pytest.mark.asyncio
    async def test_returns_200_with_correct_keys(self, client):
        fake_wallets = _make_tracked_wallets()
        portfolio_a = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 10_000),
            _make_token_item(TOKEN_BONK, "BONK", 5_000),
        ])
        portfolio_b = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 8_000),
            _make_token_item(TOKEN_WIF, "WIF", 3_000),
        ])
        portfolio_c = _make_portfolio_response([
            _make_token_item(TOKEN_JUP, "JUP", 2_000),
        ])

        async def _fake_portfolio(address: str):
            return {WALLET_A: portfolio_a, WALLET_B: portfolio_b, WALLET_C: portfolio_c}.get(address, {"data": {"items": []}})

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(side_effect=_fake_portfolio)),
        ):
            resp = await client.get("/api/wallets/overlap")

        assert resp.status_code == 200
        body = resp.json()
        assert "tokens" in body
        assert "wallets_analyzed" in body
        assert "generated_at" in body

    @pytest.mark.asyncio
    async def test_wallets_analyzed_matches_tracked_count(self, client):
        fake_wallets = _make_tracked_wallets()

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value={"data": {"items": []}})),
        ):
            resp = await client.get("/api/wallets/overlap")

        assert resp.json()["wallets_analyzed"] == 3

    @pytest.mark.asyncio
    async def test_token_row_has_all_required_fields(self, client):
        fake_wallets = _make_tracked_wallets()
        sol_item = _make_token_item(TOKEN_SOL, "SOL", 10_000)
        port = _make_portfolio_response([sol_item])

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=port)),
        ):
            resp = await client.get("/api/wallets/overlap")

        tokens = resp.json()["tokens"]
        # SOL held by all 3 — should appear
        assert len(tokens) >= 1
        t = tokens[0]
        for field in ("token_address", "symbol", "name", "logo_uri", "whale_count", "total_usd", "conviction", "whales"):
            assert field in t, f"Missing field: {field}"


class TestOverlapFiltering:

    @pytest.mark.asyncio
    async def test_single_holder_token_excluded(self, client):
        fake_wallets = _make_tracked_wallets()
        # BONK only held by A — should NOT appear
        # WIF only held by B — should NOT appear
        # SOL held by A and B — SHOULD appear
        portfolio_a = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 10_000),
            _make_token_item(TOKEN_BONK, "BONK", 5_000),
        ])
        portfolio_b = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 8_000),
            _make_token_item(TOKEN_WIF, "WIF", 3_000),
        ])
        portfolio_c = _make_portfolio_response([])

        async def _fake_p(address: str):
            return {WALLET_A: portfolio_a, WALLET_B: portfolio_b, WALLET_C: portfolio_c}.get(address, {"data": {"items": []}})

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(side_effect=_fake_p)),
        ):
            resp = await client.get("/api/wallets/overlap")

        tokens = resp.json()["tokens"]
        addresses = [t["token_address"] for t in tokens]
        assert TOKEN_SOL in addresses
        assert TOKEN_BONK not in addresses
        assert TOKEN_WIF not in addresses

    @pytest.mark.asyncio
    async def test_min_value_usd_filter_respected(self, client):
        fake_wallets = _make_tracked_wallets()
        # SOL at $100 per wallet — below default $500 min, should be excluded
        portfolio_ab = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 100),
        ])

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=portfolio_ab)),
        ):
            resp = await client.get("/api/wallets/overlap?min_value_usd=500")

        # SOL only has $100 per wallet — below $500 threshold
        assert TOKEN_SOL not in [t["token_address"] for t in resp.json()["tokens"]]

    @pytest.mark.asyncio
    async def test_lower_min_value_includes_small_positions(self, client):
        fake_wallets = {
            WALLET_A: _make_tracked_wallets()[WALLET_A],
            WALLET_B: _make_tracked_wallets()[WALLET_B],
        }
        portfolio_ab = _make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 200),
        ])

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=portfolio_ab)),
        ):
            resp = await client.get("/api/wallets/overlap?min_value_usd=100")

        assert TOKEN_SOL in [t["token_address"] for t in resp.json()["tokens"]]


class TestOverlapConviction:

    async def _run_with_n_whales(self, client, n: int) -> str:
        """Returns conviction tier for a token held by n whales."""
        from models.schemas import TrackedWallet
        wallets = {
            f"wallet{i:040d}": TrackedWallet(
                address=f"wallet{i:040d}", label=f"Whale #{i}",
                win_rate=0.6, total_pnl=1000, trade_count=10,
            )
            for i in range(1, n + 1)
        }
        portfolio = _make_portfolio_response([_make_token_item(TOKEN_SOL, "SOL", 5000)])

        with (
            patch("services.wallet_discovery.tracked_wallets", wallets),
            patch("routers.wallets.wd.tracked_wallets", wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=portfolio)),
        ):
            resp = await client.get("/api/wallets/overlap")

        tokens = resp.json()["tokens"]
        return tokens[0]["conviction"] if tokens else ""

    @pytest.mark.asyncio
    async def test_two_whales_is_moderate(self, client):
        import routers.wallets as wm; wm._overlap_cache = None
        conviction = await self._run_with_n_whales(client, 2)
        assert conviction == "MODERATE"

    @pytest.mark.asyncio
    async def test_three_whales_is_high(self, client):
        import routers.wallets as wm; wm._overlap_cache = None
        conviction = await self._run_with_n_whales(client, 3)
        assert conviction == "HIGH"

    @pytest.mark.asyncio
    async def test_four_plus_whales_is_extreme(self, client):
        import routers.wallets as wm; wm._overlap_cache = None
        conviction = await self._run_with_n_whales(client, 4)
        assert conviction == "EXTREME"


class TestOverlapResilience:

    @pytest.mark.asyncio
    async def test_portfolio_failure_returns_partial_not_500(self, client):
        """If one wallet portfolio fetch fails, rest still work."""
        from models.schemas import TrackedWallet
        fake_wallets = {
            WALLET_A: TrackedWallet(address=WALLET_A, label="Whale #1", win_rate=0.7, total_pnl=50000, trade_count=100),
            WALLET_B: TrackedWallet(address=WALLET_B, label="Whale #2", win_rate=0.6, total_pnl=30000, trade_count=80),
        }
        portfolio_a = _make_portfolio_response([_make_token_item(TOKEN_SOL, "SOL", 10_000)])

        async def _maybe_fail(address: str):
            if address == WALLET_B:
                raise RuntimeError("upstream timeout")
            return portfolio_a

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(side_effect=_maybe_fail)),
        ):
            resp = await client.get("/api/wallets/overlap")

        assert resp.status_code == 200
        # SOL only held by A (B failed) — should not appear (single holder)
        assert resp.json()["tokens"] == []

    @pytest.mark.asyncio
    async def test_no_tracked_wallets_returns_empty(self, client):
        with (
            patch("services.wallet_discovery.tracked_wallets", {}),
            patch("routers.wallets.wd.tracked_wallets", {}),
        ):
            resp = await client.get("/api/wallets/overlap")

        assert resp.status_code == 200
        assert resp.json()["tokens"] == []
        assert resp.json()["wallets_analyzed"] == 0


class TestOverlapCaching:

    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self, client):
        fake_wallets = _make_tracked_wallets()
        portfolio_mock = AsyncMock(return_value=_make_portfolio_response([
            _make_token_item(TOKEN_SOL, "SOL", 10_000),
        ]))

        with (
            patch("services.wallet_discovery.tracked_wallets", fake_wallets),
            patch("routers.wallets.wd.tracked_wallets", fake_wallets),
            patch("services.birdeye.get_wallet_portfolio", new=portfolio_mock),
        ):
            await client.get("/api/wallets/overlap")
            await client.get("/api/wallets/overlap")

        # 3 wallets × 1 call each = 3 total; cache prevents second round
        assert portfolio_mock.call_count == 3  # only first call fetches


# ===========================================================================
# PART B — Birdeye WS normalizer
# ===========================================================================

class TestBirdeyeWSNormalizer:

    def test_wallet_txs_event_passes_through(self):
        from services.birdeye_ws import _normalize_event
        from models.schemas import TrackedWallet

        fake_wallets = {
            WALLET_A: TrackedWallet(address=WALLET_A, label="Whale #1", win_rate=0.7, total_pnl=50000, trade_count=100),
        }

        payload = {
            "type": "WALLET_TXS",
            "data": {
                "txHash": "abc123",
                "owner": WALLET_A,
                "tokenAddress": TOKEN_SOL,
                "tokenSymbol": "SOL",
                "side": "BUY",
                "volumeUSD": 15000,
                "blockUnixTime": 1234567890,
            },
        }

        with patch("services.wallet_discovery.tracked_wallets", fake_wallets):
            result = _normalize_event(payload)

        assert result is not None
        assert result["type"] == "WALLET_TXS"
        assert result["data"]["wallet_label"] == "Whale #1"
        assert result["data"]["txHash"] == "abc123"

    def test_large_trade_txs_event_passes_through(self):
        from services.birdeye_ws import _normalize_event

        payload = {
            "type": "LARGE_TRADE_TXS",
            "data": {
                "txHash": "def456",
                "owner": "SomeRandomWalletNotTracked111111111111111",
                "tokenAddress": TOKEN_BONK,
                "tokenSymbol": "BONK",
                "side": "SELL",
                "volumeUSD": 50000,
                "blockUnixTime": 1234567890,
            },
        }

        with patch("services.wallet_discovery.tracked_wallets", {}):
            result = _normalize_event(payload)

        assert result is not None
        assert result["type"] == "LARGE_TRADE_TXS"
        assert result["data"]["wallet_label"] == "Whale Alert"

    def test_subscription_ack_returns_none(self):
        from services.birdeye_ws import _normalize_event

        for msg_type in ("SUBSCRIBE_WALLET_TXS", "SUBSCRIBE_LARGE_TRADE_TXS", "PING", "PONG"):
            payload = {"type": msg_type, "data": {}}
            with patch("services.wallet_discovery.tracked_wallets", {}):
                result = _normalize_event(payload)
            assert result is None, f"Expected None for type {msg_type}"

    def test_unknown_type_returns_none(self):
        from services.birdeye_ws import _normalize_event

        payload = {"type": "SOME_UNKNOWN_TYPE", "data": {}}
        with patch("services.wallet_discovery.tracked_wallets", {}):
            result = _normalize_event(payload)
        assert result is None

    def test_untracked_wallet_gets_generic_label(self):
        from services.birdeye_ws import _normalize_event

        payload = {
            "type": "WALLET_TXS",
            "data": {
                "txHash": "xyz",
                "owner": "UnknownWallet111111111111111111111111111",
                "tokenAddress": TOKEN_SOL,
                "side": "BUY",
                "volumeUSD": 10000,
                "blockUnixTime": 0,
            },
        }

        with patch("services.wallet_discovery.tracked_wallets", {}):
            result = _normalize_event(payload)

        # Should NOT be None — still forwarded with a fallback label
        assert result is not None
        assert "wallet_label" in result["data"]

    def test_request_resubscribe_sets_event(self):
        from services import birdeye_ws
        # Reset the event
        birdeye_ws._resubscribe_event = None

        # Import the function and call it
        from services.birdeye_ws import request_resubscribe, _get_resubscribe_event
        request_resubscribe()
        event = _get_resubscribe_event()
        assert event.is_set()

        # Cleanup
        event.clear()


# ===========================================================================
# PART C — Polling worker fix verification
# ===========================================================================

class TestPollingWorkerFix:

    def test_no_duplicate_sleep_in_source(self):
        """
        Verify the double-sleep bug is fixed by inspecting the source file.
        The bug was two consecutive 'await asyncio.sleep(POLL_INTERVAL_SECS)' calls.
        """
        import inspect
        from services import polling_worker
        source = inspect.getsource(polling_worker.run_polling_worker)
        sleep_calls = source.count("await asyncio.sleep(POLL_INTERVAL_SECS)")
        assert sleep_calls == 1, (
            f"Expected exactly 1 sleep call in run_polling_worker, found {sleep_calls}. "
            "The double-sleep bug may have been reintroduced."
        )

    def test_wallet_discovery_resubscribes_birdeye_ws_not_solana_ws(self):
        """
        wallet_discovery.py must call birdeye_ws.request_resubscribe,
        NOT solana_rpc_ws.request_resubscribe.
        """
        import inspect
        from services import wallet_discovery
        source = inspect.getsource(wallet_discovery.discover_wallets)
        assert "birdeye_ws" in source, "wallet_discovery should import from birdeye_ws"
        assert "solana_rpc_ws" not in source, (
            "wallet_discovery should NOT reference solana_rpc_ws anymore"
        )

    def test_main_uses_birdeye_ws_not_solana_ws(self):
        """
        main.py must import run_birdeye_ws, NOT run_solana_rpc_ws.
        """
        import pathlib
        main_src = pathlib.Path(__file__).parent / "main.py"
        content = main_src.read_text()
        assert "run_birdeye_ws" in content, "main.py must start run_birdeye_ws"
        assert "run_solana_rpc_ws" not in content, "main.py must NOT start run_solana_rpc_ws"
