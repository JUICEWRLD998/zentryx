"""
Day 6 test suite — Smart Money Trending, New Listings, Signal Profitability

Covers:
  - Route registration
  - Trending endpoint (shape, sort order, DB-unavailable fallback)
  - New listings endpoint (shape, risk derivation unit tests, UNKNOWN fallback)
  - Signal profitability endpoint (no-DB path, required keys)
  - Signal stats service (initial cache state)
  - Live Birdeye new-listings call

Run:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day6.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# ── Fixture: reset Birdeye client state before every test ─────────────────────

@pytest.fixture(autouse=True)
def reset_birdeye():
    """Prevent Birdeye singleton from leaking state between tests."""
    from services import birdeye as be
    be._client = None
    yield
    be._client = None


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ── Route Registration ─────────────────────────────────────────────────────────

def test_trending_route_exists():
    from main import app
    paths = [r.path for r in app.routes]
    assert any("trending" in p for p in paths), \
        f"No /trending route found. Routes: {paths}"


def test_new_listings_route_exists():
    from main import app
    paths = [r.path for r in app.routes]
    assert any("new-listings" in p for p in paths), \
        f"No /new-listings route found. Routes: {paths}"


def test_profitability_route_exists():
    from main import app
    paths = [r.path for r in app.routes]
    assert any("profitability" in p for p in paths), \
        f"No /stats/profitability route found. Routes: {paths}"


# ── Trending Endpoint ─────────────────────────────────────────────────────────

MOCK_TRENDING_RESPONSE = {
    "data": {
        "tokens": [
            {
                "address": "TokenAddr1111111111111111111111111111111111111",
                "symbol": "ALPHA",
                "name": "Alpha Token",
                "logoURI": "https://example.com/alpha.png",
                "price": 0.0042,
                "v24hUSD": 500_000.0,
                "liquidity": 200_000.0,
                "mc": 1_000_000.0,
            },
            {
                "address": "TokenAddr2222222222222222222222222222222222222",
                "symbol": "BETA",
                "name": "Beta Token",
                "logoURI": "",
                "price": 0.001,
                "v24hUSD": 300_000.0,
                "liquidity": 80_000.0,
                "mc": 500_000.0,
            },
        ]
    }
}


def test_trending_returns_list(client):
    """Trending endpoint should return a JSON array."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TRENDING_RESPONSE,
    ), patch("db.is_available", return_value=False):
        res = client.get("/api/trending")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)


def test_trending_shape(client):
    """Each trending item must have the expected keys."""
    required_keys = {
        "address", "symbol", "name", "logo_uri",
        "price", "volume_24h_usd", "liquidity", "market_cap",
        "smart_buy_count", "smart_score",
    }
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TRENDING_RESPONSE,
    ), patch("db.is_available", return_value=False):
        res = client.get("/api/trending")
    body = res.json()
    assert len(body) >= 1
    for item in body:
        missing = required_keys - item.keys()
        assert not missing, f"Item missing keys: {missing}"


def test_trending_no_db_fallback(client):
    """When DB is unavailable, trending still returns data with smart_buy_count=0."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TRENDING_RESPONSE,
    ), patch("db.is_available", return_value=False):
        res = client.get("/api/trending")
    body = res.json()
    assert all(item["smart_buy_count"] == 0 for item in body)


def test_trending_sort_order(client):
    """Items must be sorted by smart_score descending."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TRENDING_RESPONSE,
    ), patch("db.is_available", return_value=False):
        res = client.get("/api/trending")
    body = res.json()
    scores = [item["smart_score"] for item in body]
    assert scores == sorted(scores, reverse=True), \
        f"Items not sorted by smart_score desc: {scores}"


# ── New Listings Endpoint ─────────────────────────────────────────────────────

MOCK_LISTINGS_RESPONSE = {
    "data": {
        "items": [
            {
                "address": "ListingAddr111111111111111111111111111111111",
                "symbol": "NEWTOKEN",
                "name": "New Token",
                "decimals": 6,
                "source": "meteora_damm_v2",
                "liquidityAddedAt": "2025-01-01T06:00:00",
                "logoURI": "",
                "liquidity": 15_000.0,
            }
        ]
    }
}

MOCK_SECURITY_RESPONSE = {
    "data": {
        "freezeable": False,
        "mutableMetadata": False,
        "transferFeeEnable": False,
        "top10HolderPercent": 0.3,
    }
}


def test_new_listings_returns_list(client):
    """New listings endpoint should return a JSON array."""
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value=MOCK_LISTINGS_RESPONSE,
    ), patch(
        "services.birdeye.get_token_security",
        new_callable=AsyncMock,
        return_value=MOCK_SECURITY_RESPONSE,
    ):
        res = client.get("/api/new-listings")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_new_listings_shape(client):
    """Each new listing must have the expected keys."""
    required_keys = {
        "address", "symbol", "name", "logo_uri",
        "liquidity", "source", "age_hours",
        "freezeable", "mutable_metadata", "transfer_fee",
        "top10_holder_pct", "risk_level",
    }
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value=MOCK_LISTINGS_RESPONSE,
    ), patch(
        "services.birdeye.get_token_security",
        new_callable=AsyncMock,
        return_value=MOCK_SECURITY_RESPONSE,
    ):
        res = client.get("/api/new-listings")
    body = res.json()
    assert len(body) >= 1
    for item in body:
        missing = required_keys - item.keys()
        assert not missing, f"Item missing keys: {missing}"


# ── _derive_risk unit tests ───────────────────────────────────────────────────

def test_risk_derivation_danger():
    """freezeable + transferFeeEnable → score=4 → DANGER."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": True, "transferFeeEnable": True, "mutableMetadata": False, "top10HolderPercent": 0.2}
    assert _derive_risk(sec) == "DANGER"


def test_risk_derivation_risky():
    """Only mutableMetadata → score=1 → RISKY."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": False, "mutableMetadata": True, "top10HolderPercent": 0.2}
    assert _derive_risk(sec) == "RISKY"


def test_risk_derivation_safe():
    """All clean flags → score=0 → SAFE."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": False, "mutableMetadata": False, "top10HolderPercent": 0.3}
    assert _derive_risk(sec) == "SAFE"


def test_risk_derivation_high_holder_concentration_risky():
    """top10HolderPercent > 0.8 alone → score=1 → RISKY."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": False, "mutableMetadata": False, "top10HolderPercent": 0.95}
    assert _derive_risk(sec) == "RISKY"


def test_new_listings_unknown_risk(client):
    """When security fetch returns empty dict, risk_level should be UNKNOWN."""
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value=MOCK_LISTINGS_RESPONSE,
    ), patch(
        "services.birdeye.get_token_security",
        new_callable=AsyncMock,
        return_value={"data": {}},
    ):
        res = client.get("/api/new-listings")
    body = res.json()
    assert len(body) >= 1
    # Empty sec dict → _derive_risk returns UNKNOWN
    assert body[0]["risk_level"] == "UNKNOWN"


# ── Signal Profitability Endpoint ─────────────────────────────────────────────

PROFITABILITY_REQUIRED_KEYS = {
    "computed_at", "total_signals", "profitable",
    "win_rate", "avg_return_pct", "top_performers",
}


def test_profitability_no_db(client):
    """When DB is unavailable and cache is empty, returns 200 with total_signals=0."""
    import services.signal_stats as ss
    ss._cache = None  # ensure cache is clear

    with patch("db.is_available", return_value=False):
        res = client.get("/api/stats/profitability")
    assert res.status_code == 200
    body = res.json()
    assert body["total_signals"] == 0


def test_profitability_cache_keys(client):
    """Response must contain all required top-level keys."""
    import services.signal_stats as ss
    ss._cache = None  # ensure cache is clear

    with patch("db.is_available", return_value=False):
        res = client.get("/api/stats/profitability")
    body = res.json()
    missing = PROFITABILITY_REQUIRED_KEYS - body.keys()
    assert not missing, f"Response missing keys: {missing}"


def test_profitability_top_performers_is_list(client):
    """top_performers must always be a list (empty when no data)."""
    import services.signal_stats as ss
    ss._cache = None

    with patch("db.is_available", return_value=False):
        res = client.get("/api/stats/profitability")
    body = res.json()
    assert isinstance(body["top_performers"], list)


# ── Signal Stats Service ───────────────────────────────────────────────────────

def test_signal_stats_cache_initially_none():
    """get_cached_stats() must return None until calculate_signal_profitability() runs."""
    import services.signal_stats as ss
    ss._cache = None  # reset any leftover state
    assert ss.get_cached_stats() is None


def test_signal_stats_cache_stores_result():
    """After manually setting _cache, get_cached_stats() returns it unchanged."""
    import services.signal_stats as ss
    fake = {"total_signals": 5, "win_rate": 60.0}
    ss._cache = fake
    assert ss.get_cached_stats() is fake
    ss._cache = None  # cleanup


# ── Live Birdeye New Listings call ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_new_listings():
    """Real Birdeye API call — verifies at least one listing with symbol and liquidity."""
    from services import birdeye as be
    res = await be.get_new_listings(limit=5, offset=0)
    data = res.get("data") or []
    # API returns either {"items": [...]} or a direct list
    if isinstance(data, dict):
        items = data.get("items") or []
    else:
        items = data
    assert isinstance(items, list), f"Expected list, got {type(items)}"
    assert len(items) >= 1, "Expected at least 1 new listing from Birdeye"
    item = items[0]
    assert "symbol" in item, f"Missing 'symbol' in first item: {list(item.keys())}"
    assert "liquidity" in item, f"Missing 'liquidity' in first item: {list(item.keys())}"
