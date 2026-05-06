"""
Day 5 tests — Portfolio X-Ray + Smart Money Heatmap.

Run: pytest test_day5.py -v
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from main import app
import services.birdeye as be

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_birdeye_client():
    """Reset the shared httpx client between tests to avoid event-loop conflicts."""
    be._client = None
    yield
    if be._client is not None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(be._client.aclose())
        except Exception:
            pass
    be._client = None


@pytest.fixture
def client():
    return TestClient(app)


# ── Router import & registration ────────────────────────────────────────────

def test_wallets_router_has_portfolio_route():
    from routers.wallets import router
    paths = [r.path for r in router.routes]
    assert "/api/wallets/{address}/portfolio" in paths


def test_tokens_router_has_heatmap_route():
    from routers.tokens import router
    paths = [r.path for r in router.routes]
    assert "/api/heatmap" in paths


def test_tokens_router_has_overlap_route():
    from routers.tokens import router
    paths = [r.path for r in router.routes]
    assert "/api/tokens/overlap" in paths


# ── Portfolio endpoint ───────────────────────────────────────────────────────

MOCK_TOKEN_LIST_RESPONSE = {
    "data": {
        "items": [
            {
                "address": "So11111111111111111111111111111111111111112",
                "decimals": 9,
                "balance": 5_000_000_000,
                "uiAmount": 5.0,
                "chainId": "solana",
                "name": "Wrapped SOL",
                "symbol": "SOL",
                "icon": "",
                "logoURI": "https://example.com/sol.png",
                "priceUsd": 145.0,
                "valueUsd": 725.0,
                "isScaledUiToken": False,
                "multiplier": None,
            },
            {
                "address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "decimals": 6,
                "balance": 1_000_000,
                "uiAmount": 1.0,
                "chainId": "solana",
                "name": "USD Coin",
                "symbol": "USDC",
                "icon": "",
                "logoURI": "",
                "priceUsd": 1.0,
                "valueUsd": 1.0,
                "isScaledUiToken": False,
                "multiplier": None,
            },
        ]
    }
}


def test_portfolio_maps_fields(client):
    with patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=MOCK_TOKEN_LIST_RESPONSE)):
        resp = client.get("/api/wallets/TestWalletAddress123/portfolio")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) == 2
    # Sorted descending by usd_value
    assert items[0]["symbol"] == "SOL"
    assert items[0]["usd_value"] == 725.0
    assert items[0]["amount"] == 5.0
    assert items[0]["price_usd"] == 145.0
    assert items[0]["logo_uri"] == "https://example.com/sol.png"


def test_portfolio_allocation_pct_sums_to_100(client):
    with patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=MOCK_TOKEN_LIST_RESPONSE)):
        resp = client.get("/api/wallets/TestWalletAddress123/portfolio")
    items = resp.json()
    total = sum(i["allocation_pct"] for i in items)
    assert abs(total - 100.0) < 0.5  # rounding tolerance


def test_portfolio_filters_dust(client):
    """Items with valueUsd < 0.01 should be excluded."""
    dust_response = {
        "data": {
            "items": [
                {**MOCK_TOKEN_LIST_RESPONSE["data"]["items"][0]},
                {
                    "address": "dust_token",
                    "decimals": 9,
                    "balance": 1,
                    "uiAmount": 0.000000001,
                    "chainId": "solana",
                    "name": "Dust",
                    "symbol": "DUST",
                    "icon": "",
                    "logoURI": "",
                    "priceUsd": 0.0001,
                    "valueUsd": 0.000000001,
                    "isScaledUiToken": False,
                    "multiplier": None,
                },
            ]
        }
    }
    with patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value=dust_response)):
        resp = client.get("/api/wallets/TestWalletAddress123/portfolio")
    items = resp.json()
    symbols = [i["symbol"] for i in items]
    assert "DUST" not in symbols
    assert "SOL" in symbols


def test_portfolio_empty_wallet(client):
    with patch("services.birdeye.get_wallet_portfolio", new=AsyncMock(return_value={"data": {"items": []}})):
        resp = client.get("/api/wallets/EmptyWallet/portfolio")
    assert resp.status_code == 200
    assert resp.json() == []


# ── Heatmap endpoint ─────────────────────────────────────────────────────────

def test_heatmap_no_db(client):
    """When DB is unavailable, heatmap returns empty structure."""
    import db
    original = db.is_available
    db.is_available = lambda: False
    try:
        resp = client.get("/api/heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tokens"] == []
        assert data["buckets"] == []
        assert data["cells"] == []
    finally:
        db.is_available = original


def test_heatmap_response_shape(client):
    """Response always has required keys."""
    import db
    db.is_available = lambda: False
    try:
        resp = client.get("/api/heatmap")
        data = resp.json()
        assert "tokens" in data
        assert "buckets" in data
        assert "cells" in data
        assert "bucket_hours" in data
    finally:
        import importlib
        importlib.reload(db)


# ── Overlap endpoint ─────────────────────────────────────────────────────────

def test_overlap_no_db(client):
    """When DB is unavailable, overlap returns empty list."""
    import db
    original = db.is_available
    db.is_available = lambda: False
    try:
        resp = client.get("/api/tokens/overlap")
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        db.is_available = original


# ── Live Birdeye portfolio call ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_portfolio_known_whale():
    """Live call: DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh has holdings."""
    raw = await be.get_wallet_portfolio("DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh")
    items = (raw.get("data") or {}).get("items") or []
    assert len(items) > 0, "Expected non-empty portfolio for known whale"
    first = items[0]
    assert "symbol" in first
    assert "valueUsd" in first
    assert "uiAmount" in first
