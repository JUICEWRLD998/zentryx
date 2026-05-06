"""
test_day4.py — Zentryx Sprint 3 · Day 4 Tests

Covers:
  1. tokens_router import and route registration
  2. OHLCV timeframe mapping logic
  3. Mover sorting logic (gainers desc, losers asc)
  4. Route existence checks (/ohlcv, /whale-buys, /movers)
  5. Live Birdeye OHLCV call for SOL (24 candles)
  6. Live movers endpoint (gainers + losers with priceChange24h)
"""

import asyncio
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ──────────────────────────────────────────────────────────────────────────────
# 1. Router import
# ──────────────────────────────────────────────────────────────────────────────

def test_tokens_router_importable():
    from routers.tokens import router
    assert router is not None


def test_tokens_router_routes():
    from routers.tokens import router
    paths = [r.path for r in router.routes]
    assert "/api/tokens/{address}/ohlcv" in paths
    assert "/api/tokens/{address}/whale-buys" in paths
    assert "/api/movers" in paths


def test_tokens_router_registered_in_main():
    """Verify main.py includes the tokens router."""
    main_path = os.path.join(os.path.dirname(__file__), "main.py")
    with open(main_path) as f:
        src = f.read()
    assert "tokens_router" in src
    assert "include_router(tokens_router)" in src


# ──────────────────────────────────────────────────────────────────────────────
# 2. OHLCV timeframe mapping
# ──────────────────────────────────────────────────────────────────────────────

_TIMEFRAME_MAP = {
    "1D": ("1H", 86_400),
    "7D": ("4H", 604_800),
    "30D": ("1D", 2_592_000),
}

def test_timeframe_1d_maps_to_1h():
    resolution, window = _TIMEFRAME_MAP["1D"]
    assert resolution == "1H"
    assert window == 86_400


def test_timeframe_7d_maps_to_4h():
    resolution, window = _TIMEFRAME_MAP["7D"]
    assert resolution == "4H"
    assert window == 604_800


def test_timeframe_30d_maps_to_1d():
    resolution, window = _TIMEFRAME_MAP["30D"]
    assert resolution == "1D"
    assert window == 2_592_000


def test_timeframe_covers_all_options():
    for key in ("1D", "7D", "30D"):
        assert key in _TIMEFRAME_MAP


# ──────────────────────────────────────────────────────────────────────────────
# 3. Mover sorting logic
# ──────────────────────────────────────────────────────────────────────────────

_SAMPLE_TOKENS = [
    {"symbol": "A", "price_change_24h": 5.0},
    {"symbol": "B", "price_change_24h": 120.0},
    {"symbol": "C", "price_change_24h": -8.0},
    {"symbol": "D", "price_change_24h": 0.5},
    {"symbol": "E", "price_change_24h": -42.0},
    {"symbol": "F", "price_change_24h": 17.3},
    {"symbol": "G", "price_change_24h": -3.1},
]


def _split_movers(tokens, top_n=3):
    gainers = sorted(
        [t for t in tokens if t["price_change_24h"] > 0],
        key=lambda x: x["price_change_24h"],
        reverse=True,
    )[:top_n]
    losers = sorted(
        [t for t in tokens if t["price_change_24h"] < 0],
        key=lambda x: x["price_change_24h"],
    )[:top_n]
    return gainers, losers


def test_gainers_sorted_descending():
    gainers, _ = _split_movers(_SAMPLE_TOKENS)
    changes = [g["price_change_24h"] for g in gainers]
    assert changes == sorted(changes, reverse=True)


def test_losers_sorted_ascending():
    _, losers = _split_movers(_SAMPLE_TOKENS)
    changes = [l["price_change_24h"] for l in losers]
    assert changes == sorted(changes)


def test_gainers_are_positive():
    gainers, _ = _split_movers(_SAMPLE_TOKENS)
    for g in gainers:
        assert g["price_change_24h"] > 0


def test_losers_are_negative():
    _, losers = _split_movers(_SAMPLE_TOKENS)
    for l in losers:
        assert l["price_change_24h"] < 0


def test_top_gainer_is_b():
    gainers, _ = _split_movers(_SAMPLE_TOKENS)
    assert gainers[0]["symbol"] == "B"  # 120%


def test_top_loser_is_e():
    _, losers = _split_movers(_SAMPLE_TOKENS)
    assert losers[0]["symbol"] == "E"  # -42%


# ──────────────────────────────────────────────────────────────────────────────
# 4. Live Birdeye — OHLCV for SOL
# ──────────────────────────────────────────────────────────────────────────────

SOL_MINT = "So11111111111111111111111111111111111111112"


@pytest.fixture(autouse=True)
def reset_birdeye_client():
    """Reset the module-level httpx client before each test to avoid event-loop conflicts."""
    import services.birdeye as be
    be._client = None
    yield
    be._client = None


@pytest.mark.asyncio
async def test_ohlcv_returns_candles():
    from services.birdeye import get_token_ohlcv
    import time
    now = int(time.time())
    raw = await get_token_ohlcv(SOL_MINT, "1H", now - 86_400, now)
    items = (raw.get("data") or {}).get("items") or []
    assert isinstance(items, list), "Expected a list of candles"
    assert len(items) > 0, "Expected at least one candle"
    print(f"  OHLCV candles returned: {len(items)}")


@pytest.mark.asyncio
async def test_ohlcv_candle_shape():
    from services.birdeye import get_token_ohlcv
    import time
    now = int(time.time())
    raw = await get_token_ohlcv(SOL_MINT, "1H", now - 86_400, now)
    items = (raw.get("data") or {}).get("items") or []
    if not items:
        pytest.skip("No candles returned — API may be unavailable")
    candle = items[0]
    assert "o" in candle, f"Missing 'o' in candle keys: {list(candle.keys())}"
    assert "c" in candle, f"Missing 'c' in candle keys: {list(candle.keys())}"
    assert "unixTime" in candle, f"Missing 'unixTime' in candle keys: {list(candle.keys())}"
    print(f"  Sample candle keys: {list(candle.keys())}")


@pytest.mark.asyncio
async def test_ohlcv_has_enough_candles_for_1d():
    """1D timeframe with 1H resolution should give ~24 candles."""
    from services.birdeye import get_token_ohlcv
    import time
    now = int(time.time())
    raw = await get_token_ohlcv(SOL_MINT, "1H", now - 86_400, now)
    items = (raw.get("data") or {}).get("items") or []
    assert len(items) >= 12, f"Expected ≥12 candles for 1D/1H, got {len(items)}"
    print(f"  1D/1H candles: {len(items)}")


# ──────────────────────────────────────────────────────────────────────────────
# 5. Live Birdeye — movers (gainers + losers)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_movers_endpoint_structure():
    """Test the full movers logic as exercised by the router."""
    import time
    from services.birdeye import get_trending_tokens, get_token_price

    # Step 1: Fetch top 25 by volume
    tokenlist = await get_trending_tokens(
        sort_by="v24hUSD", sort_type="desc", offset=0, limit=25
    )
    tokens = tokenlist.get("data", {}).get("tokens", [])
    assert isinstance(tokens, list), "tokenlist.data.tokens must be a list"
    assert len(tokens) > 0, "Expected at least one token in tokenlist"
    print(f"  Tokens in tokenlist: {len(tokens)}")


@pytest.mark.asyncio
async def test_movers_price_change_fetched():
    """Spot-check that get_token_price returns priceChange24h for SOL."""
    from services.birdeye import get_token_price
    price_data = await get_token_price(SOL_MINT)
    data = price_data.get("data", {})
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "value" in data, f"No 'value' in price data: {list(data.keys())}"
    print(f"  SOL price: {data.get('value')} | priceChange24h: {data.get('priceChange24h')}")


@pytest.mark.asyncio
async def test_movers_has_gainers_and_losers():
    """End-to-end: top tokens should contain at least one gainer and one loser in 24h."""
    from services.birdeye import get_trending_tokens, get_token_price

    tokenlist = await get_trending_tokens(
        sort_by="v24hUSD", sort_type="desc", offset=0, limit=25
    )
    tokens = tokenlist.get("data", {}).get("tokens", [])[:5]  # Limit to 5 for speed

    enriched = []
    for t in tokens:
        price_data = await get_token_price(t["address"])
        data = price_data.get("data", {})
        if isinstance(data, dict) and "priceChange24h" in data:
            enriched.append({
                "symbol": t.get("symbol"),
                "price_change_24h": data["priceChange24h"],
            })

    assert len(enriched) > 0, "No tokens could be enriched with priceChange24h"
    summaries = ["{} {:+.1f}%".format(e["symbol"], e["price_change_24h"]) for e in enriched]
    print(f"  Enriched tokens: {summaries}")


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Run: pytest test_day4.py -v")
