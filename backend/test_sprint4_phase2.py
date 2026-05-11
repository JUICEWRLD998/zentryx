"""
Sprint 4 Phase 2 — Tests for the Smart Money Signal Heatmap.

Verifies that:
  1. GET /api/smart-money/heatmap returns HTTP 200 with the correct shape.
  2. Each token row has address, symbol, name, logo_uri, signal, buy_usd, sell_usd, net_usd.
  3. Signal is BUY when buy > sell, SELL when sell > buy, NEUTRAL when equal.
  4. Tokens with no buy/sell data default to BUY (on the list = accumulating).
  5. Empty token list from Birdeye returns {"tokens": [], ...}.
  6. The birdeye wrapper get_smart_money_inflow_outflow is still callable.
  7. The heatmap honors the `limit` query parameter.

Route under test:
  GET /api/smart-money/heatmap

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_sprint4_phase2.py -v
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_A = "So11111111111111111111111111111111111111112"
TOKEN_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Token list with explicit buy/sell volume fields
_TOKEN_LIST_WITH_VOLUME = {
    "data": {
        "items": [
            {
                "token": TOKEN_A,
                "symbol": "SOL",
                "name": "Wrapped SOL",
                "logoURI": "https://example.com/sol.png",
                "buy": 500_000.0,
                "sell": 200_000.0,
            },
            {
                "token": TOKEN_B,
                "symbol": "USDC",
                "name": "USD Coin",
                "logoURI": "https://example.com/usdc.png",
                "buy": 100_000.0,
                "sell": 400_000.0,
            },
        ]
    }
}

# Token list with NO buy/sell fields — should default to BUY signal
_TOKEN_LIST_NO_VOLUME = {
    "data": {
        "items": [
            {
                "token": TOKEN_A,
                "symbol": "SOL",
                "name": "Wrapped SOL",
                "logoURI": "https://example.com/sol.png",
            },
            {
                "token": TOKEN_B,
                "symbol": "USDC",
                "name": "USD Coin",
                "logoURI": "https://example.com/usdc.png",
            },
        ]
    }
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_route_cache():
    """Reset the in-process heatmap cache between tests."""
    import routers.smart_money as sm_module
    sm_module._cache = None
    yield
    sm_module._cache = None


@pytest.fixture()
async def client():
    """Yield an AsyncClient pointed at the FastAPI app (no real I/O)."""
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ===========================================================================
# 1. Basic shape tests
# ===========================================================================

class TestHeatmapRoute:

    @pytest.mark.asyncio
    async def test_returns_200_with_tokens_key(self, client):
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        body = resp.json()
        assert "tokens" in body
        assert "generated_at" in body

    @pytest.mark.asyncio
    async def test_token_row_has_all_required_fields(self, client):
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        assert len(tokens) == 2
        token = tokens[0]
        for field in ("address", "symbol", "name", "logo_uri", "signal", "buy_usd", "sell_usd", "net_usd"):
            assert field in token, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_signal_is_buy_when_buy_exceeds_sell(self, client):
        """TOKEN_A has buy=500k > sell=200k → signal should be BUY."""
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        sol = next(t for t in tokens if t["symbol"] == "SOL")
        assert sol["signal"] == "BUY"
        assert sol["buy_usd"] == 500_000.0
        assert sol["sell_usd"] == 200_000.0
        assert sol["net_usd"] == pytest.approx(300_000.0, abs=1)

    @pytest.mark.asyncio
    async def test_signal_is_sell_when_sell_exceeds_buy(self, client):
        """TOKEN_B has sell=400k > buy=100k → signal should be SELL."""
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        usdc = next(t for t in tokens if t["symbol"] == "USDC")
        assert usdc["signal"] == "SELL"
        assert usdc["net_usd"] == pytest.approx(-300_000.0, abs=1)

    @pytest.mark.asyncio
    async def test_signal_defaults_to_buy_when_no_volume_data(self, client):
        """Tokens with no buy/sell fields default to BUY (on the list = accumulating)."""
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_NO_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        assert len(tokens) == 2
        for t in tokens:
            assert t["signal"] == "BUY"
            assert t["buy_usd"] == 0.0
            assert t["sell_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_token_symbol_mapped_correctly(self, client):
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        symbols = {t["symbol"] for t in tokens}
        assert "SOL" in symbols
        assert "USDC" in symbols


# ===========================================================================
# 2. Error resilience
# ===========================================================================

class TestHeatmapErrorHandling:

    @pytest.mark.asyncio
    async def test_empty_token_list_returns_empty_tokens(self, client):
        empty = {"data": {"items": []}}
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=empty)):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        assert resp.json()["tokens"] == []

    @pytest.mark.asyncio
    async def test_token_list_failure_returns_502(self, client):
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(side_effect=RuntimeError("API down"))):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_items_without_token_address_are_skipped(self, client):
        """Items that have no address field are silently dropped."""
        bad_list = {
            "data": {
                "items": [
                    {"token": "", "symbol": "BAD"},
                    {"token": TOKEN_A, "symbol": "SOL"},
                ]
            }
        }
        with patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=bad_list)):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        tokens = resp.json()["tokens"]
        assert len(tokens) == 1
        assert tokens[0]["symbol"] == "SOL"


# ===========================================================================
# 3. Caching
# ===========================================================================

class TestHeatmapCaching:

    @pytest.mark.asyncio
    async def test_second_call_does_not_re_fetch_birdeye(self, client):
        """Result is served from cache on the second call."""
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)

        with patch("services.birdeye.get_smart_money_tokens", new=mock_token_list):
            resp1 = await client.get("/api/smart-money/heatmap")
            resp2 = await client.get("/api/smart-money/heatmap")

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Token list should only be called ONCE (cache served the second)
        assert mock_token_list.call_count == 1


# ===========================================================================
# 4. Limit query param
# ===========================================================================

class TestHeatmapLimitParam:

    @pytest.mark.asyncio
    async def test_limit_passed_to_birdeye(self, client):
        """limit query param is passed through to get_smart_money_tokens."""
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)
        with patch("services.birdeye.get_smart_money_tokens", new=mock_token_list):
            await client.get("/api/smart-money/heatmap?limit=5")

        mock_token_list.assert_called_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_limit_clamped_to_50(self, client):
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)
        with patch("services.birdeye.get_smart_money_tokens", new=mock_token_list):
            await client.get("/api/smart-money/heatmap?limit=999")

        _, kwargs = mock_token_list.call_args
        assert kwargs["limit"] <= 50

    @pytest.mark.asyncio
    async def test_limit_minimum_is_1(self, client):
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_WITH_VOLUME)
        with patch("services.birdeye.get_smart_money_tokens", new=mock_token_list):
            await client.get("/api/smart-money/heatmap?limit=0")

        _, kwargs = mock_token_list.call_args
        assert kwargs["limit"] >= 1


# ===========================================================================
# 5. _compute_signal unit tests
# ===========================================================================

class TestComputeSignal:

    def test_buy_greater_than_sell_returns_buy(self):
        from routers.smart_money import _compute_signal
        signal, buy, sell, net = _compute_signal({"buy": 1000.0, "sell": 400.0})
        assert signal == "BUY"
        assert net == pytest.approx(600.0)

    def test_sell_greater_than_buy_returns_sell(self):
        from routers.smart_money import _compute_signal
        signal, buy, sell, net = _compute_signal({"buy": 100.0, "sell": 800.0})
        assert signal == "SELL"
        assert net == pytest.approx(-700.0)

    def test_equal_buy_sell_returns_neutral(self):
        from routers.smart_money import _compute_signal
        signal, buy, sell, net = _compute_signal({"buy": 500.0, "sell": 500.0})
        assert signal == "NEUTRAL"
        assert net == pytest.approx(0.0)

    def test_no_volume_data_defaults_to_buy(self):
        from routers.smart_money import _compute_signal
        signal, buy, sell, net = _compute_signal({})
        assert signal == "BUY"
        assert buy == 0.0
        assert sell == 0.0

    def test_net_field_overrides_computed_value(self):
        from routers.smart_money import _compute_signal
        signal, buy, sell, net = _compute_signal({"buy": 1000.0, "sell": 600.0, "netBuy": -50.0})
        assert signal == "SELL"  # netBuy < 0 → SELL
        assert net == pytest.approx(-50.0)


# ===========================================================================
# 6. Birdeye wrapper smoke test (function still exists in birdeye.py)
# ===========================================================================

class TestSmartMoneyBirdeyeWrapper:

    @pytest.mark.asyncio
    async def test_wrapper_exists_and_is_callable(self):
        from services.birdeye import get_smart_money_inflow_outflow
        assert callable(get_smart_money_inflow_outflow)

    @pytest.mark.asyncio
    async def test_wrapper_calls_correct_endpoint(self):
        from services import birdeye

        captured: list[str] = []

        async def fake_get(path: str, params=None):
            captured.append(path)
            return {"data": {"buyAmount": 1000.0, "sellAmount": 500.0}}

        with patch("services.birdeye._get", new=fake_get):
            await birdeye.get_smart_money_inflow_outflow(TOKEN_A, time_frame="4H")

        assert captured == ["/smart-money/v1/token/inflow-outflow"]

    @pytest.mark.asyncio
    async def test_wrapper_passes_time_frame_param(self):
        from services import birdeye

        captured_params: list[dict] = []

        async def fake_get(path: str, params=None):
            captured_params.append(params or {})
            return {"data": {}}

        with patch("services.birdeye._get", new=fake_get):
            await birdeye.get_smart_money_inflow_outflow(TOKEN_A, time_frame="1H")

        assert captured_params[0].get("type") == "1H"

    @pytest.mark.asyncio
    async def test_wrapper_passes_address_param(self):
        from services import birdeye

        captured_params: list[dict] = []

        async def fake_get(path: str, params=None):
            captured_params.append(params or {})
            return {"data": {}}

        with patch("services.birdeye._get", new=fake_get):
            await birdeye.get_smart_money_inflow_outflow(TOKEN_A, time_frame="24H")

        assert captured_params[0].get("address") == TOKEN_A
