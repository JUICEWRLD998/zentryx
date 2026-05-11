"""
Sprint 4 Phase 2 — Tests for the Smart Money Inflow/Outflow Heatmap.

Verifies that:
  1. GET /api/smart-money/heatmap returns HTTP 200 with the correct shape.
  2. Each token row contains the required 1h/4h/24h flow buckets.
  3. Each bucket has inflow, outflow, and net fields.
  4. The endpoint tolerates Birdeye failures gracefully (returns zeros, not 500).
  5. Empty token list from Birdeye returns {"tokens": [], ...}.
  6. The new birdeye wrapper get_smart_money_inflow_outflow is callable.
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

_TOKEN_LIST_RESPONSE = {
    "data": {
        "items": [
            {
                "address": TOKEN_A,
                "symbol": "SOL",
                "name": "Wrapped SOL",
                "logoURI": "https://example.com/sol.png",
            },
            {
                "address": TOKEN_B,
                "symbol": "USDC",
                "name": "USD Coin",
                "logoURI": "https://example.com/usdc.png",
            },
        ]
    }
}

_INFLOW_RESPONSE = {
    "data": {
        "buyAmount": 500_000.0,
        "sellAmount": 200_000.0,
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
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        body = resp.json()
        assert "tokens" in body
        assert "generated_at" in body

    @pytest.mark.asyncio
    async def test_token_row_has_all_required_fields(self, client):
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        tokens = resp.json()["tokens"]
        assert len(tokens) == 2
        token = tokens[0]
        assert "address" in token
        assert "symbol" in token
        assert "name" in token
        assert "logo_uri" in token
        for frame in ("1h", "4h", "24h"):
            assert frame in token, f"Missing frame key: {frame}"

    @pytest.mark.asyncio
    async def test_flow_bucket_has_inflow_outflow_net(self, client):
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        token = resp.json()["tokens"][0]
        for frame in ("1h", "4h", "24h"):
            bucket = token[frame]
            assert "inflow" in bucket
            assert "outflow" in bucket
            assert "net" in bucket

    @pytest.mark.asyncio
    async def test_net_equals_inflow_minus_outflow(self, client):
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        token = resp.json()["tokens"][0]
        for frame in ("1h", "4h", "24h"):
            b = token[frame]
            assert abs(b["net"] - (b["inflow"] - b["outflow"])) < 0.01, (
                f"net != inflow - outflow for frame {frame}"
            )

    @pytest.mark.asyncio
    async def test_token_symbol_mapped_correctly(self, client):
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
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
    async def test_flow_fetch_failure_returns_zeros_not_500(self, client):
        """If individual flow calls fail, the row still appears with zero values."""
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(side_effect=RuntimeError("upstream down"))),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        tokens = resp.json()["tokens"]
        assert len(tokens) == 2
        for t in tokens:
            for frame in ("1h", "4h", "24h"):
                assert t[frame]["net"] == 0.0

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
    async def test_malformed_inflow_response_defaults_to_zero(self, client):
        """Birdeye returns an unexpected shape — should not crash."""
        with (
            patch("services.birdeye.get_smart_money_tokens", new=AsyncMock(return_value=_TOKEN_LIST_RESPONSE)),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value={"data": {}})),
        ):
            resp = await client.get("/api/smart-money/heatmap")

        assert resp.status_code == 200
        for t in resp.json()["tokens"]:
            for frame in ("1h", "4h", "24h"):
                assert t[frame]["inflow"] == 0.0
                assert t[frame]["outflow"] == 0.0


# ===========================================================================
# 3. Caching
# ===========================================================================

class TestHeatmapCaching:

    @pytest.mark.asyncio
    async def test_second_call_does_not_re_fetch_birdeye(self, client):
        """Result is served from cache on the second call."""
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_RESPONSE)
        mock_flow = AsyncMock(return_value=_INFLOW_RESPONSE)

        with (
            patch("services.birdeye.get_smart_money_tokens", new=mock_token_list),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=mock_flow),
        ):
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
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_RESPONSE)
        with (
            patch("services.birdeye.get_smart_money_tokens", new=mock_token_list),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            await client.get("/api/smart-money/heatmap?limit=5")

        mock_token_list.assert_called_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_limit_clamped_to_50(self, client):
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_RESPONSE)
        with (
            patch("services.birdeye.get_smart_money_tokens", new=mock_token_list),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            await client.get("/api/smart-money/heatmap?limit=999")

        _, kwargs = mock_token_list.call_args
        assert kwargs["limit"] <= 50

    @pytest.mark.asyncio
    async def test_limit_minimum_is_1(self, client):
        mock_token_list = AsyncMock(return_value=_TOKEN_LIST_RESPONSE)
        with (
            patch("services.birdeye.get_smart_money_tokens", new=mock_token_list),
            patch("services.birdeye.get_smart_money_inflow_outflow", new=AsyncMock(return_value=_INFLOW_RESPONSE)),
        ):
            await client.get("/api/smart-money/heatmap?limit=0")

        _, kwargs = mock_token_list.call_args
        assert kwargs["limit"] >= 1


# ===========================================================================
# 5. Birdeye wrapper smoke test
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
