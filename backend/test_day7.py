"""
Day 7 test suite — Shared NavBar, Price Ticker Data, Regression

Covers:
  - NavBar component file exists on disk
  - /api/movers  shape, gainers/losers keys, sort order, ticker compatibility
  - New listings deduplication (duplicate address → only 1 result)
  - _derive_risk edge cases not covered in Day 6:
      · freezeable-only  → DANGER (score=2)
      · fee-only         → DANGER (score=2)
      · holder boundary (exactly 0.80) → SAFE (not strictly > 0.80)
      · None holder pct  → treated as 0 → SAFE
  - Regression: trending, new-listings, profitability still return 200

Run:
    cd backend && .venv\\Scripts\\python.exe -m pytest test_day7.py -v
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_birdeye():
    from services import birdeye as be
    be._client = None
    yield
    be._client = None


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ── 1. NavBar component file exists ───────────────────────────────────────────

NAVBAR_PATH = os.path.join(
    os.path.dirname(__file__),   # backend/
    "..",                         # project root
    "components",
    "navbar.tsx",
)


def test_navbar_file_exists():
    """components/navbar.tsx must exist on disk after Day 7 scaffold."""
    assert os.path.isfile(NAVBAR_PATH), (
        f"NavBar component not found at: {os.path.abspath(NAVBAR_PATH)}"
    )


def test_navbar_exports_navbar_function():
    """navbar.tsx must export a NavBar function/component (exported symbol check)."""
    with open(NAVBAR_PATH, encoding="utf-8") as f:
        src = f.read()
    assert "export function NavBar" in src, \
        "navbar.tsx does not contain 'export function NavBar'"


def test_navbar_has_sheet_import():
    """NavBar must use the Sheet component for the mobile hamburger menu."""
    with open(NAVBAR_PATH, encoding="utf-8") as f:
        src = f.read()
    assert "Sheet" in src, "navbar.tsx does not import/use Sheet"


def test_navbar_has_active_page_prop():
    """NavBar must accept activePage prop for per-page active highlighting."""
    with open(NAVBAR_PATH, encoding="utf-8") as f:
        src = f.read()
    assert "activePage" in src, "navbar.tsx does not define activePage prop"


# ── 2. /api/movers route ──────────────────────────────────────────────────────

def test_movers_route_exists():
    from main import app
    paths = [r.path for r in app.routes]
    assert any("movers" in p for p in paths), \
        f"No /movers route found. Routes: {paths}"


MOCK_TOKEN_LIST = {
    "data": {
        "tokens": [
            {
                "address": "MoverAddr1111111111111111111111111111111111",
                "symbol": "ALPHA",
                "name": "Alpha Token",
                "logoURI": "https://example.com/alpha.png",
                "price": 0.005,
                "v24hUSD": 900_000.0,
                "liquidity": 300_000.0,
                "mc": 2_000_000.0,
            },
            {
                "address": "MoverAddr2222222222222222222222222222222222",
                "symbol": "BETA",
                "name": "Beta Token",
                "logoURI": "",
                "price": 0.002,
                "v24hUSD": 400_000.0,
                "liquidity": 100_000.0,
                "mc": 800_000.0,
            },
            {
                "address": "MoverAddr3333333333333333333333333333333333",
                "symbol": "GAMMA",
                "name": "Gamma Token",
                "logoURI": "",
                "price": 0.001,
                "v24hUSD": 200_000.0,
                "liquidity": 50_000.0,
                "mc": 300_000.0,
            },
        ]
    }
}

# Simulated price changes: ALPHA=+12%, BETA=-5%, GAMMA=+3%
MOCK_PRICE_CHANGES = {
    "MoverAddr1111111111111111111111111111111111": {"data": {"priceChange24h": 12.0}},
    "MoverAddr2222222222222222222222222222222222": {"data": {"priceChange24h": -5.0}},
    "MoverAddr3333333333333333333333333333333333": {"data": {"priceChange24h": 3.0}},
}


def _make_price_mock(changes: dict):
    """Return an AsyncMock side_effect that returns price data keyed by address."""
    async def _get_price(address: str):
        return changes.get(address, {})
    return _get_price


def test_movers_returns_gainers_and_losers(client):
    """Response must be a dict with 'gainers' and 'losers' list keys."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(MOCK_PRICE_CHANGES),
    ):
        res = client.get("/api/movers")
    assert res.status_code == 200
    body = res.json()
    assert "gainers" in body, "Response missing 'gainers' key"
    assert "losers" in body, "Response missing 'losers' key"
    assert isinstance(body["gainers"], list)
    assert isinstance(body["losers"], list)


def test_movers_item_shape(client):
    """Each mover must have all fields the ticker + UI require."""
    required_keys = {
        "address", "symbol", "name", "price",
        "price_change_24h", "volume_24h_usd", "liquidity",
        "market_cap", "logo_uri",
    }
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(MOCK_PRICE_CHANGES),
    ):
        res = client.get("/api/movers")
    body = res.json()
    all_items = body["gainers"] + body["losers"]
    assert len(all_items) > 0, "No items returned in gainers or losers"
    for item in all_items:
        missing = required_keys - item.keys()
        assert not missing, f"Mover item missing keys: {missing}"


def test_movers_gainers_sorted_descending(client):
    """Gainers must be sorted by price_change_24h descending."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(MOCK_PRICE_CHANGES),
    ):
        res = client.get("/api/movers")
    gainers = res.json()["gainers"]
    if len(gainers) > 1:
        changes = [g["price_change_24h"] for g in gainers]
        assert changes == sorted(changes, reverse=True), \
            f"Gainers not sorted descending: {changes}"


def test_movers_losers_are_negative(client):
    """All losers must have price_change_24h < 0."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(MOCK_PRICE_CHANGES),
    ):
        res = client.get("/api/movers")
    losers = res.json()["losers"]
    for item in losers:
        assert item["price_change_24h"] < 0, \
            f"Loser has non-negative price change: {item['price_change_24h']}"


def test_movers_losers_sorted_ascending(client):
    """Losers must be sorted by price_change_24h ascending (most negative first)."""
    changes_multi = {
        "MoverAddr1111111111111111111111111111111111": {"data": {"priceChange24h": -2.0}},
        "MoverAddr2222222222222222222222222222222222": {"data": {"priceChange24h": -15.0}},
        "MoverAddr3333333333333333333333333333333333": {"data": {"priceChange24h": -8.0}},
    }
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(changes_multi),
    ):
        res = client.get("/api/movers")
    losers = res.json()["losers"]
    if len(losers) > 1:
        vals = [l["price_change_24h"] for l in losers]
        assert vals == sorted(vals), f"Losers not sorted ascending: {vals}"


def test_movers_price_change_field_is_numeric(client):
    """price_change_24h must be a float/int (ticker relies on toFixed())."""
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(MOCK_PRICE_CHANGES),
    ):
        res = client.get("/api/movers")
    body = res.json()
    for item in body["gainers"] + body["losers"]:
        assert isinstance(item["price_change_24h"], (int, float)), \
            f"price_change_24h is not numeric: {item['price_change_24h']!r}"


def test_movers_skips_tokens_with_no_price_data(client):
    """Tokens whose price fetch returns None should be excluded from results."""
    # Only ALPHA has a real price change; BETA and GAMMA return empty dicts
    sparse_changes = {
        "MoverAddr1111111111111111111111111111111111": {"data": {"priceChange24h": 7.5}},
        # BETA and GAMMA intentionally omitted → _fetch_price_change returns None
    }
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TOKEN_LIST,
    ), patch(
        "services.birdeye.get_token_price",
        side_effect=_make_price_mock(sparse_changes),
    ):
        res = client.get("/api/movers")
    body = res.json()
    all_items = body["gainers"] + body["losers"]
    addresses = [item["address"] for item in all_items]
    assert "MoverAddr1111111111111111111111111111111111" in addresses
    assert "MoverAddr2222222222222222222222222222222222" not in addresses
    assert "MoverAddr3333333333333333333333333333333333" not in addresses


# ── 3. New listings deduplication ─────────────────────────────────────────────

MOCK_DUPLICATE_LISTINGS_RESPONSE = {
    "data": {
        "items": [
            {
                "address": "DupAddr111111111111111111111111111111111111",
                "symbol": "DUPTKN",
                "name": "Duplicate Token",
                "logoURI": "",
                "liquidity": 50_000,
                "liquidityAddedAt": "2025-01-01T00:00:00",
                "source": "raydium",
            },
            # same address again — must be deduplicated
            {
                "address": "DupAddr111111111111111111111111111111111111",
                "symbol": "DUPTKN",
                "name": "Duplicate Token",
                "logoURI": "",
                "liquidity": 50_000,
                "liquidityAddedAt": "2025-01-01T00:00:00",
                "source": "raydium",
            },
            {
                "address": "UniqueAddr22222222222222222222222222222222222",
                "symbol": "UNIQUE",
                "name": "Unique Token",
                "logoURI": "",
                "liquidity": 30_000,
                "liquidityAddedAt": "2025-01-01T00:00:00",
                "source": "orca",
            },
        ]
    }
}


def test_new_listings_deduplication(client):
    """When Birdeye returns duplicate addresses, the response must contain each address only once."""
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value=MOCK_DUPLICATE_LISTINGS_RESPONSE,
    ), patch(
        "services.birdeye.get_token_security",
        new_callable=AsyncMock,
        return_value={"data": {}},
    ):
        res = client.get("/api/new-listings")
    assert res.status_code == 200
    body = res.json()
    addresses = [item["address"] for item in body]
    assert len(addresses) == len(set(addresses)), \
        f"Duplicate addresses in response: {addresses}"


def test_new_listings_deduplication_count(client):
    """3 items with 1 duplicate → exactly 2 unique items in response."""
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value=MOCK_DUPLICATE_LISTINGS_RESPONSE,
    ), patch(
        "services.birdeye.get_token_security",
        new_callable=AsyncMock,
        return_value={"data": {}},
    ):
        res = client.get("/api/new-listings")
    body = res.json()
    assert len(body) == 2, \
        f"Expected 2 deduplicated items, got {len(body)}"


# ── 4. _derive_risk edge cases ────────────────────────────────────────────────

def test_risk_freezeable_only_is_danger():
    """freezeable alone scores +2 → DANGER (boundary: score exactly 2)."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": True, "transferFeeEnable": False, "mutableMetadata": False, "top10HolderPercent": 0.1}
    assert _derive_risk(sec) == "DANGER"


def test_risk_transfer_fee_only_is_danger():
    """transferFeeEnable alone scores +2 → DANGER."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": True, "mutableMetadata": False, "top10HolderPercent": 0.1}
    assert _derive_risk(sec) == "DANGER"


def test_risk_holder_boundary_exactly_80pct_is_safe():
    """top10HolderPercent == 0.80 (not strictly >0.80) → score unchanged → SAFE."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": False, "mutableMetadata": False, "top10HolderPercent": 0.80}
    assert _derive_risk(sec) == "SAFE"


def test_risk_holder_none_treated_as_zero():
    """top10HolderPercent=None → treated as 0 (or clause) → does not increment score."""
    from routers.tokens import _derive_risk
    sec = {"freezeable": False, "transferFeeEnable": False, "mutableMetadata": False, "top10HolderPercent": None}
    assert _derive_risk(sec) == "SAFE"


# ── 5. Regression — existing routes still return 200 ─────────────────────────

MOCK_TRENDING_MINIMAL = {
    "data": {
        "tokens": [
            {
                "address": "RegrAddr1111111111111111111111111111111111",
                "symbol": "REG",
                "name": "Regression Token",
                "logoURI": "",
                "price": 0.001,
                "v24hUSD": 100_000.0,
                "liquidity": 50_000.0,
                "mc": 200_000.0,
            }
        ]
    }
}


def test_regression_trending_still_200(client):
    with patch(
        "services.birdeye.get_trending_tokens",
        new_callable=AsyncMock,
        return_value=MOCK_TRENDING_MINIMAL,
    ), patch("db.is_available", return_value=False):
        res = client.get("/api/trending")
    assert res.status_code == 200


def test_regression_new_listings_still_200(client):
    with patch(
        "services.birdeye.get_new_listings",
        new_callable=AsyncMock,
        return_value={"data": {"items": []}},
    ):
        res = client.get("/api/new-listings")
    assert res.status_code == 200


def test_regression_profitability_still_200(client):
    import services.signal_stats as ss
    ss._cache = None
    with patch("db.is_available", return_value=False):
        res = client.get("/api/stats/profitability")
    assert res.status_code == 200
