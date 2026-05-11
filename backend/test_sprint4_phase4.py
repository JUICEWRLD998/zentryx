"""
Sprint 4 Phase 4 — Tests for Signal Profitability API.

Covers:
  PART A — GET /api/signals/stats
    1. Returns 200 with correct shape when cache is cold (None → zeroed payload)
    2. Returns 200 with live stats when cache is populated
    3. win_rate, total_signals, profitable, avg_return_pct, top_performers present
    4. top_performers items have required fields
    5. computed_at is null when cold, ISO string when warm

  PART B — signal_stats.get_cached_stats() integration
    6. Route passes through whatever get_cached_stats() returns verbatim
    7. Route returns zeroed dict (not 500) when cache is None

Run with:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_sprint4_phase4.py -v
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
async def client():
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ===========================================================================
# PART A — Route shape
# ===========================================================================

class TestSignalStatsRoute:

    @pytest.mark.asyncio
    async def test_cold_cache_returns_200_not_503(self, client):
        """When signal_stats cache is None, route must return 200 with zeroed payload."""
        with patch("services.signal_stats.get_cached_stats", return_value=None):
            resp = await client.get("/api/signals/stats")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_cold_cache_returns_zeroed_shape(self, client):
        with patch("services.signal_stats.get_cached_stats", return_value=None):
            body = (await client.get("/api/signals/stats")).json()
        assert body["total_signals"] == 0
        assert body["profitable"] == 0
        assert body["win_rate"] == 0.0
        assert body["avg_return_pct"] == 0.0
        assert body["top_performers"] == []
        assert body["computed_at"] is None

    @pytest.mark.asyncio
    async def test_warm_cache_returns_real_data(self, client):
        fake_stats = {
            "computed_at": "2026-05-01T09:00:00+00:00",
            "total_signals": 20,
            "profitable": 13,
            "win_rate": 65.0,
            "avg_return_pct": 12.5,
            "top_performers": [
                {
                    "address": "So11111111111111111111111111111111111111112",
                    "symbol": "SOL",
                    "entry_usd": 180.0,
                    "current_price": 220.0,
                    "return_pct": 22.22,
                }
            ],
        }
        with patch("services.signal_stats.get_cached_stats", return_value=fake_stats):
            body = (await client.get("/api/signals/stats")).json()

        assert body["total_signals"] == 20
        assert body["profitable"] == 13
        assert body["win_rate"] == 65.0
        assert body["avg_return_pct"] == 12.5
        assert len(body["top_performers"]) == 1

    @pytest.mark.asyncio
    async def test_top_performers_have_required_fields(self, client):
        fake_stats = {
            "computed_at": "2026-05-01T09:00:00+00:00",
            "total_signals": 5,
            "profitable": 3,
            "win_rate": 60.0,
            "avg_return_pct": 8.0,
            "top_performers": [
                {
                    "address": "TokenAddr111",
                    "symbol": "BONK",
                    "entry_usd": 0.0001,
                    "current_price": 0.0002,
                    "return_pct": 100.0,
                }
            ],
        }
        with patch("services.signal_stats.get_cached_stats", return_value=fake_stats):
            body = (await client.get("/api/signals/stats")).json()

        performer = body["top_performers"][0]
        for field in ("address", "symbol", "entry_usd", "current_price", "return_pct"):
            assert field in performer, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_computed_at_is_null_when_cold(self, client):
        with patch("services.signal_stats.get_cached_stats", return_value=None):
            body = (await client.get("/api/signals/stats")).json()
        assert body["computed_at"] is None

    @pytest.mark.asyncio
    async def test_computed_at_is_string_when_warm(self, client):
        fake_stats = {
            "computed_at": "2026-05-01T09:00:00+00:00",
            "total_signals": 1,
            "profitable": 1,
            "win_rate": 100.0,
            "avg_return_pct": 5.0,
            "top_performers": [],
        }
        with patch("services.signal_stats.get_cached_stats", return_value=fake_stats):
            body = (await client.get("/api/signals/stats")).json()
        assert isinstance(body["computed_at"], str)
        assert "2026" in body["computed_at"]

    @pytest.mark.asyncio
    async def test_passthrough_verbatim(self, client):
        """Route must return exactly what get_cached_stats() returns, no transformation."""
        custom = {
            "computed_at": "custom",
            "total_signals": 999,
            "profitable": 500,
            "win_rate": 50.05,
            "avg_return_pct": -3.14,
            "top_performers": [],
        }
        with patch("services.signal_stats.get_cached_stats", return_value=custom):
            body = (await client.get("/api/signals/stats")).json()
        assert body["win_rate"] == 50.05
        assert body["avg_return_pct"] == -3.14
        assert body["total_signals"] == 999
