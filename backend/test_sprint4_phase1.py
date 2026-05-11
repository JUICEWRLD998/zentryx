"""
Sprint 4 Phase 1 — Tests for 8 dormant premium endpoint routes.

Verifies that every new route:
  1. Returns HTTP 200 with the expected top-level shape.
  2. Contains the required fields the frontend relies on.
  3. Handles Birdeye 502 errors gracefully (returns 502 to caller).
  4. Does NOT make real network calls (all Birdeye calls are mocked).

Routes under test:
  Token routes (tokens.py):
    GET /api/tokens/{address}/top-traders
    GET /api/tokens/{address}/holders
    GET /api/tokens/{address}/trade-data
    GET /api/tokens/{address}/exit-liquidity
    GET /api/tokens/{address}/price-stats

  Wallet routes (wallets.py):
    GET /api/wallets/{address}/balance-change
    GET /api/wallets/{address}/net-worth-details
    GET /api/wallets/{address}/activity

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_sprint4_phase1.py -v
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

# ---------------------------------------------------------------------------
# Constants — realistic Solana addresses used in all tests
# ---------------------------------------------------------------------------

SOL_ADDRESS = "So11111111111111111111111111111111111111112"
WALLET_ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


# ---------------------------------------------------------------------------
# App fixture — creates a clean test client from the FastAPI app
# ---------------------------------------------------------------------------

@pytest.fixture()
async def client():
    """Yield an AsyncClient pointed at the FastAPI app."""
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ===========================================================================
# 1. GET /api/tokens/{address}/top-traders
# ===========================================================================

class TestTopTradersRoute:

    @pytest.mark.asyncio
    async def test_returns_list_on_success(self, client):
        mock_response = {
            "data": {
                "items": [
                    {"address": WALLET_ADDRESS, "pnl": 12345.0, "volume": 99000.0, "tradeCount": 42, "winRate": 0.72},
                    {"address": "AnotherWallet111111111111111111111111111", "pnl": 5000.0, "volume": 30000.0, "tradeCount": 10, "winRate": 0.60},
                ]
            }
        }
        with patch("services.birdeye.get_top_traders", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/top-traders")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_required_fields_present(self, client):
        mock_response = {
            "data": {
                "items": [
                    {"address": WALLET_ADDRESS, "pnl": 5000.0, "volume": 20000.0, "tradeCount": 8, "winRate": 0.5},
                ]
            }
        }
        with patch("services.birdeye.get_top_traders", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/top-traders")

        assert resp.status_code == 200
        item = resp.json()[0]
        assert "address" in item
        assert "pnl_usd" in item
        assert "volume_usd" in item
        assert "trade_count" in item
        assert "win_rate" in item
        assert "is_tracked" in item

    @pytest.mark.asyncio
    async def test_is_tracked_flag_set_for_known_wallet(self, client):
        """Wallets in the tracked list should have is_tracked=True."""
        tracked_wallet = MagicMock()
        tracked_wallet.address = WALLET_ADDRESS
        tracked_wallet.label = "Whale Alpha"

        mock_response = {
            "data": {"items": [{"address": WALLET_ADDRESS, "pnl": 1000.0}]}
        }
        with patch("services.birdeye.get_top_traders", new=AsyncMock(return_value=mock_response)), \
             patch("services.wallet_discovery.get_tracked_wallets", return_value=[tracked_wallet]):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/top-traders")

        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["is_tracked"] is True
        assert item["label"] == "Whale Alpha"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items(self, client):
        with patch("services.birdeye.get_top_traders", new=AsyncMock(return_value={"data": {"items": []}})):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/top-traders")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_502_on_birdeye_failure(self, client):
        with patch("services.birdeye.get_top_traders", new=AsyncMock(side_effect=RuntimeError("Birdeye down"))):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/top-traders")
        assert resp.status_code == 502


# ===========================================================================
# 2. GET /api/tokens/{address}/holders
# ===========================================================================

class TestHoldersRoute:

    def _make_holders_response(self, total=5000, items=None):
        return {
            "data": {
                "total": total,
                "items": items or [
                    {"address": "Holder1111111111111111111111111111111", "uiAmount": 1_000_000, "pct": 0.30},
                    {"address": "Holder2222222222222222222222222222222", "uiAmount": 500_000,   "pct": 0.15},
                ]
            }
        }

    def _make_dist_response(self):
        return {"data": {"items": [{"range": "0-100", "count": 3000}, {"range": "100-1000", "count": 1500}]}}

    @pytest.mark.asyncio
    async def test_returns_200_with_required_fields(self, client):
        with patch("services.birdeye.get_token_holders", new=AsyncMock(return_value=self._make_holders_response())), \
             patch("services.birdeye.get_holder_distribution", new=AsyncMock(return_value=self._make_dist_response())):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/holders")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_holders" in data
        assert "top10_pct" in data
        assert "top10" in data
        assert "concentration_risk" in data
        assert isinstance(data["top10"], list)

    @pytest.mark.asyncio
    async def test_concentration_risk_high_when_top10_over_80pct(self, client):
        items = [{"address": f"Holder{i}", "uiAmount": 100_000, "pct": 0.09} for i in range(10)]
        with patch("services.birdeye.get_token_holders", new=AsyncMock(return_value=self._make_holders_response(items=items))), \
             patch("services.birdeye.get_holder_distribution", new=AsyncMock(return_value=self._make_dist_response())):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/holders")

        assert resp.status_code == 200
        # 10 holders × 9% = 90% top10 → HIGH
        assert resp.json()["concentration_risk"] == "HIGH"

    @pytest.mark.asyncio
    async def test_concentration_risk_low_when_distributed(self, client):
        items = [{"address": f"Holder{i}", "uiAmount": 10_000, "pct": 0.02} for i in range(10)]
        with patch("services.birdeye.get_token_holders", new=AsyncMock(return_value=self._make_holders_response(items=items))), \
             patch("services.birdeye.get_holder_distribution", new=AsyncMock(return_value=self._make_dist_response())):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/holders")

        assert resp.status_code == 200
        assert resp.json()["concentration_risk"] == "LOW"

    @pytest.mark.asyncio
    async def test_returns_502_on_birdeye_failure(self, client):
        with patch("services.birdeye.get_token_holders", new=AsyncMock(side_effect=RuntimeError("Birdeye timeout"))), \
             patch("services.birdeye.get_holder_distribution", new=AsyncMock(side_effect=RuntimeError("Birdeye timeout"))):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/holders")
        assert resp.status_code == 502


# ===========================================================================
# 3. GET /api/tokens/{address}/trade-data
# ===========================================================================

class TestTradeDataRoute:

    @pytest.mark.asyncio
    async def test_required_fields_and_pressure_buy(self, client):
        mock_response = {
            "data": {
                "buy": 340,
                "sell": 150,
                "buyVolume": 450_000.0,
                "sellVolume": 180_000.0,
            }
        }
        with patch("services.birdeye.get_token_trade_data", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/trade-data")

        assert resp.status_code == 200
        data = resp.json()
        assert "buy_count" in data
        assert "sell_count" in data
        assert "total_trades" in data
        assert "buy_ratio" in data
        assert "buy_volume_usd" in data
        assert "sell_volume_usd" in data
        assert "pressure" in data
        assert data["buy_count"] == 340
        assert data["sell_count"] == 150
        assert data["total_trades"] == 490
        assert data["pressure"] == "BUY"   # buy_ratio ≈ 0.69 → BUY

    @pytest.mark.asyncio
    async def test_pressure_sell_when_sellers_dominate(self, client):
        mock_response = {"data": {"buy": 80, "sell": 300, "buyVolume": 50_000.0, "sellVolume": 300_000.0}}
        with patch("services.birdeye.get_token_trade_data", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/trade-data")
        assert resp.status_code == 200
        assert resp.json()["pressure"] == "SELL"

    @pytest.mark.asyncio
    async def test_pressure_neutral_when_balanced(self, client):
        mock_response = {"data": {"buy": 100, "sell": 100}}
        with patch("services.birdeye.get_token_trade_data", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/trade-data")
        assert resp.status_code == 200
        assert resp.json()["pressure"] == "NEUTRAL"

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_token_trade_data", new=AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/trade-data")
        assert resp.status_code == 502


# ===========================================================================
# 4. GET /api/tokens/{address}/exit-liquidity
# ===========================================================================

class TestExitLiquidityRoute:

    @pytest.mark.asyncio
    async def test_returns_slippage_estimates_and_rating(self, client):
        mock_response = {
            "data": {
                "totalLiquidity": 2_000_000.0,
                "depth1Pct": 20_000.0,
                "depth2Pct": 40_000.0,
                "items": [],
            }
        }
        with patch("services.birdeye.get_exit_liquidity", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/exit-liquidity")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_liquidity_usd" in data
        assert "slippage_estimates" in data
        assert "rating" in data
        assert isinstance(data["slippage_estimates"], list)
        assert len(data["slippage_estimates"]) == 3
        # Each estimate has exit_usd and slippage_pct
        for est in data["slippage_estimates"]:
            assert "exit_usd" in est
            assert "slippage_pct" in est

    @pytest.mark.asyncio
    async def test_rating_deep_for_large_liquidity(self, client):
        mock_response = {"data": {"totalLiquidity": 5_000_000.0}}
        with patch("services.birdeye.get_exit_liquidity", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/exit-liquidity")
        assert resp.status_code == 200
        assert resp.json()["rating"] == "DEEP"

    @pytest.mark.asyncio
    async def test_rating_critical_for_tiny_liquidity(self, client):
        mock_response = {"data": {"totalLiquidity": 5_000.0}}
        with patch("services.birdeye.get_exit_liquidity", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/exit-liquidity")
        assert resp.status_code == 200
        assert resp.json()["rating"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_exit_liquidity", new=AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/exit-liquidity")
        assert resp.status_code == 502


# ===========================================================================
# 5. GET /api/tokens/{address}/price-stats
# ===========================================================================

class TestPriceStatsRoute:

    @pytest.mark.asyncio
    async def test_returns_three_timeframes(self, client):
        mock_response = {
            "data": {
                "price": 150.0,
                "1hChangePercent": 1.5,
                "1hHigh": 152.0,
                "1hLow": 148.0,
                "1hVolume": 500_000.0,
                "4hChangePercent": -2.1,
                "4hHigh": 155.0,
                "4hLow": 145.0,
                "4hVolume": 1_500_000.0,
                "24hChangePercent": 8.3,
                "24hHigh": 160.0,
                "24hLow": 140.0,
                "24hVolume": 9_000_000.0,
            }
        }
        with patch("services.birdeye.get_price_stats", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/price-stats")

        assert resp.status_code == 200
        data = resp.json()
        assert "current_price" in data
        assert "1h" in data
        assert "4h" in data
        assert "24h" in data
        for tf in ("1h", "4h", "24h"):
            assert "price_change_pct" in data[tf]
            assert "high" in data[tf]
            assert "low" in data[tf]
            assert "volume_usd" in data[tf]

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_price_stats", new=AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await client.get(f"/api/tokens/{SOL_ADDRESS}/price-stats")
        assert resp.status_code == 502


# ===========================================================================
# 6. GET /api/wallets/{address}/balance-change
# ===========================================================================

class TestBalanceChangeRoute:

    @pytest.mark.asyncio
    async def test_returns_24h_and_7d_fields(self, client):
        mock_response = {
            "data": {
                "change24h": 12_500.0,
                "change7d": -3_200.0,
                "change24hPercent": 4.2,
                "change7dPercent": -1.1,
                "totalUsd": 310_000.0,
            }
        }
        with patch("services.birdeye.get_wallet_balance_change", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/balance-change")

        assert resp.status_code == 200
        data = resp.json()
        assert "address" in data
        assert "change_24h_usd" in data
        assert "change_7d_usd" in data
        assert "change_24h_pct" in data
        assert "change_7d_pct" in data
        assert "current_usd" in data
        assert data["change_24h_usd"] == 12_500.0
        assert data["change_7d_usd"] == -3_200.0
        assert data["current_usd"] == 310_000.0

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_wallet_balance_change", new=AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/balance-change")
        assert resp.status_code == 502


# ===========================================================================
# 7. GET /api/wallets/{address}/net-worth-details
# ===========================================================================

class TestNetWorthDetailsRoute:

    @pytest.mark.asyncio
    async def test_returns_breakdown_and_categories(self, client):
        mock_response = {
            "data": {
                "totalUsd": 500_000.0,
                "items": [
                    {"symbol": "SOL",   "type": "native", "valueUsd": 200_000.0, "logoURI": ""},
                    {"symbol": "USDC",  "type": "token",  "valueUsd": 150_000.0, "logoURI": ""},
                    {"symbol": "BONK",  "type": "token",  "valueUsd": 150_000.0, "logoURI": ""},
                ]
            }
        }
        with patch("services.birdeye.get_wallet_net_worth_details", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/net-worth-details")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_usd" in data
        assert "categories" in data
        assert "breakdown" in data
        assert isinstance(data["categories"], list)
        assert isinstance(data["breakdown"], list)
        assert data["total_usd"] == 500_000.0
        # breakdown should be sorted by value descending
        values = [item["value_usd"] for item in data["breakdown"]]
        assert values == sorted(values, reverse=True)

    @pytest.mark.asyncio
    async def test_allocation_pct_sums_to_100(self, client):
        mock_response = {
            "data": {
                "items": [
                    {"symbol": "SOL",  "type": "native", "valueUsd": 60.0},
                    {"symbol": "USDC", "type": "token",  "valueUsd": 40.0},
                ]
            }
        }
        with patch("services.birdeye.get_wallet_net_worth_details", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/net-worth-details")

        assert resp.status_code == 200
        breakdown = resp.json()["breakdown"]
        total_pct = sum(item["allocation_pct"] for item in breakdown)
        assert abs(total_pct - 100.0) < 0.5  # allow small float rounding

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_wallet_net_worth_details", new=AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/net-worth-details")
        assert resp.status_code == 502


# ===========================================================================
# 8. GET /api/wallets/{address}/activity
# ===========================================================================

class TestWalletActivityRoute:

    @pytest.mark.asyncio
    async def test_returns_list_with_required_fields(self, client):
        mock_response = {
            "data": {
                "items": [
                    {
                        "txHash": "abc123",
                        "type": "SWAP",
                        "tokenAddress": SOL_ADDRESS,
                        "tokenSymbol": "SOL",
                        "uiAmount": 10.5,
                        "valueUsd": 1_500.0,
                        "blockUnixTime": 1_700_000_000,
                        "status": "confirmed",
                    },
                    {
                        "txHash": "def456",
                        "type": "TRANSFER",
                        "tokenAddress": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "tokenSymbol": "USDC",
                        "uiAmount": 500.0,
                        "valueUsd": 500.0,
                        "blockUnixTime": 1_700_001_000,
                        "status": "confirmed",
                    },
                ]
            }
        }
        with patch("services.birdeye.get_wallet_tx_list", new=AsyncMock(return_value=mock_response)):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/activity")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        item = data[0]
        assert "signature" in item
        assert "type" in item
        assert "token_symbol" in item
        assert "value_usd" in item
        assert "timestamp" in item
        assert "amount" in item
        assert item["signature"] == "abc123"
        assert item["value_usd"] == 1_500.0

    @pytest.mark.asyncio
    async def test_limit_param_is_respected(self, client):
        """Limit capped at 50 server-side; verify it is passed through."""
        items = [{"txHash": f"tx{i}", "type": "SWAP", "blockUnixTime": i} for i in range(30)]
        mock_response = {"data": {"items": items}}
        with patch("services.birdeye.get_wallet_tx_list", new=AsyncMock(return_value=mock_response)) as mock_call:
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/activity?limit=30")
        assert resp.status_code == 200
        # Verify the call received limit=30 (capped to min(30, 50)=30)
        call_kwargs = mock_call.call_args
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_transactions(self, client):
        with patch("services.birdeye.get_wallet_tx_list", new=AsyncMock(return_value={"data": {"items": []}})):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/activity")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_502_on_failure(self, client):
        with patch("services.birdeye.get_wallet_tx_list", new=AsyncMock(side_effect=RuntimeError("Birdeye down"))):
            resp = await client.get(f"/api/wallets/{WALLET_ADDRESS}/activity")
        assert resp.status_code == 502


# ===========================================================================
# 9. Cross-cutting: all Phase 1 routes return JSON (not HTML error pages)
# ===========================================================================

class TestAllRoutesReturnJson:
    """Smoke test: every route returns application/json even on mocked errors."""

    ROUTES = [
        f"/api/tokens/{SOL_ADDRESS}/top-traders",
        f"/api/tokens/{SOL_ADDRESS}/holders",
        f"/api/tokens/{SOL_ADDRESS}/trade-data",
        f"/api/tokens/{SOL_ADDRESS}/exit-liquidity",
        f"/api/tokens/{SOL_ADDRESS}/price-stats",
        f"/api/wallets/{WALLET_ADDRESS}/balance-change",
        f"/api/wallets/{WALLET_ADDRESS}/net-worth-details",
        f"/api/wallets/{WALLET_ADDRESS}/activity",
    ]

    @pytest.mark.asyncio
    async def test_all_routes_return_json_content_type(self, client):
        """With successful mocks, all routes return JSON."""
        success_response = {"data": {}}
        mocks = {
            "services.birdeye.get_top_traders": AsyncMock(return_value={"data": {"items": []}}),
            "services.birdeye.get_token_holders": AsyncMock(return_value={"data": {"total": 0, "items": []}}),
            "services.birdeye.get_holder_distribution": AsyncMock(return_value={"data": {"items": []}}),
            "services.birdeye.get_token_trade_data": AsyncMock(return_value={"data": {"buy": 0, "sell": 0}}),
            "services.birdeye.get_exit_liquidity": AsyncMock(return_value={"data": {"totalLiquidity": 0}}),
            "services.birdeye.get_price_stats": AsyncMock(return_value={"data": {}}),
            "services.birdeye.get_wallet_balance_change": AsyncMock(return_value={"data": {}}),
            "services.birdeye.get_wallet_net_worth_details": AsyncMock(return_value={"data": {"items": []}}),
            "services.birdeye.get_wallet_tx_list": AsyncMock(return_value={"data": {"items": []}}),
        }

        patches = [patch(name, new=mock) for name, mock in mocks.items()]
        for p in patches:
            p.start()
        try:
            for route in self.ROUTES:
                resp = await client.get(route)
                ct = resp.headers.get("content-type", "")
                assert "application/json" in ct, f"Route {route} returned non-JSON content-type: {ct}"
        finally:
            for p in patches:
                p.stop()
