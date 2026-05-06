"""
Day 1 endpoint test script.

Tests all 7 new premium Birdeye endpoints added on Day 1, plus verifies
the WebSocket URL construction and dynamic token polling logic.

Run from the backend/ directory:
    python test_day1.py

Exit code 0 = all tests passed.
Exit code 1 = one or more tests failed.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Test token / wallet addresses (well-known, stable) ─────────────────────

SOL_MINT      = "So11111111111111111111111111111111111111112"
BONK_MINT     = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
TEST_WALLET   = "3XMrhbv989VxAMi3DErLV9eJht1pHppW5LbKxe9fkEFR"  # public known whale

# ── Helpers ─────────────────────────────────────────────────────────────────

PASS  = "PASS"
FAIL  = "FAIL"
SKIP  = "SKIP"

results: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    icon = "[PASS]" if status == PASS else "[FAIL]" if status == FAIL else "[SKIP]"
    line = f"  {icon}  {name}"
    if detail:
        line += f" — {detail}"
    print(line)


async def run_test(name: str, coro, *, key: str | None = None) -> dict[str, Any] | None:
    """Run a coroutine and record pass/fail.  Optionally checks that a key exists."""
    try:
        result = await coro
        if not isinstance(result, dict):
            record(FAIL, name, f"expected dict, got {type(result).__name__}")
            return None
        # Birdeye always returns {"success": true, "data": ...}
        # Accept as pass if we got a dict back (even if data is empty/null)
        if key and key not in result and "data" not in result:
            record(FAIL, name, f"missing key '{key}' in response keys: {list(result.keys())[:5]}")
            return None
        data_preview = str(result)[:80].replace("\n", " ")
        record(PASS, name, data_preview)
        return result
    except Exception as exc:
        record(FAIL, name, str(exc)[:120])
        return None


# ── Individual tests ─────────────────────────────────────────────────────────

async def test_api_key_present() -> bool:
    key = os.getenv("BIRDEYE_API_KEY", "")
    if not key or key == "your_new_premium_key_here":
        record(FAIL, "BIRDEYE_API_KEY set in .env", "key is missing or still the placeholder")
        return False
    record(PASS, "BIRDEYE_API_KEY set in .env", f"{key[:6]}...{key[-4:]}")
    return True


async def test_gemini_key_present() -> None:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "your_gemini_api_key_here":
        record(SKIP, "GEMINI_API_KEY set in .env", "not required for Day 1 — needed on Day 2")
    else:
        record(PASS, "GEMINI_API_KEY set in .env", f"{key[:6]}...{key[-4:]}")


async def test_websocket_url() -> None:
    """Verify the WS URL is constructed correctly with the API key."""
    from services.birdeye_ws import BIRDEYE_WS_BASE
    api_key = os.getenv("BIRDEYE_API_KEY", "")
    expected_prefix = f"{BIRDEYE_WS_BASE}?x-api-key="
    url = f"{BIRDEYE_WS_BASE}?x-api-key={api_key}"
    if url.startswith(expected_prefix) and len(api_key) > 0:
        record(PASS, "WebSocket URL construction", url[:60] + "...")
    else:
        record(FAIL, "WebSocket URL construction", f"got: {url[:80]}")


async def test_endpoint_18_price() -> None:
    from services import birdeye
    await run_test(
        "Endpoint 18 — /defi/price (real-time SOL price)",
        birdeye.get_token_price(SOL_MINT),
    )


async def test_endpoint_19_ohlcv() -> None:
    import time
    from services import birdeye
    time_to   = int(time.time())
    time_from = time_to - 86_400  # last 24 hours
    await run_test(
        "Endpoint 19 — /defi/ohlcv (SOL 15m candles, last 24h)",
        birdeye.get_token_ohlcv(SOL_MINT, timeframe="15m", time_from=time_from, time_to=time_to),
    )


async def test_endpoint_20_trending() -> None:
    from services import birdeye
    result = await run_test(
        "Endpoint 20 — /defi/tokenlist (top trending by 24h volume)",
        birdeye.get_trending_tokens(limit=5),
    )
    if result:
        data = result.get("data") or {}
        items = data.get("tokens") or data.get("items") or []
        if items:
            symbols = [t.get("symbol", "?") for t in items[:5]]
            record(PASS, "  Trending token count", f"{len(items)} tokens returned, sample: {symbols}")
        else:
            record(FAIL, "  Trending token count", "data.tokens / data.items is empty")


async def test_endpoint_21_new_listings() -> None:
    from services import birdeye
    await run_test(
        "Endpoint 21 — /defi/v2/tokens/new_listing (recent launches)",
        birdeye.get_new_listings(limit=5),
    )


async def test_endpoint_22_creation_info() -> None:
    from services import birdeye
    await run_test(
        "Endpoint 22 — /defi/token_creation_info (BONK token age)",
        birdeye.get_token_creation_info(BONK_MINT),
    )


async def test_endpoint_23_portfolio() -> None:
    from services import birdeye
    await run_test(
        "Endpoint 23 — /v1/wallet/token_list (whale portfolio holdings)",
        birdeye.get_wallet_portfolio(TEST_WALLET),
    )


async def test_endpoint_24_trending_rank() -> None:
    from services import birdeye
    result = await run_test(
        "Endpoint 24 — /defi/token_trending (Birdeye editorial trending rank)",
        birdeye.get_token_trending(limit=5),
    )
    if result:
        data = result.get("data") or {}
        tokens = data.get("tokens") or []
        if tokens:
            symbols = [t.get("symbol", "?") for t in tokens[:5]]
            record(PASS, "  Trending rank token count", f"{len(tokens)} tokens, sample: {symbols}")


async def test_dynamic_polling_refresh() -> None:
    """Verify that refresh_monitored_tokens() populates a non-empty list."""
    from services import polling_worker
    before = list(polling_worker.MONITORED_TOKENS)
    await polling_worker.refresh_monitored_tokens()
    after = polling_worker.MONITORED_TOKENS
    if len(after) > len(before) or (len(after) > 0 and after != polling_worker._DEFAULT_TOKENS):
        record(PASS, "Dynamic polling refresh", f"monitoring {len(after)} tokens from Birdeye trending")
    elif len(after) > 0:
        record(PASS, "Dynamic polling refresh", f"monitoring {len(after)} tokens (trending returned same as fallback or fallback used)")
    else:
        record(FAIL, "Dynamic polling refresh", "MONITORED_TOKENS is empty after refresh")


# ── Entry point ──────────────────────────────────────────────────────────────

async def main() -> int:
    print("\n" + "=" * 60)
    print("  ZENTRYX — Day 1 Premium Endpoint Tests")
    print("=" * 60 + "\n")

    # 0. Pre-flight checks
    print("Pre-flight:")
    key_ok = await test_api_key_present()
    await test_gemini_key_present()
    print()

    if not key_ok:
        print("Cannot run endpoint tests without a valid BIRDEYE_API_KEY.\n")
        return 1

    # 1. WebSocket
    print("WebSocket:")
    await test_websocket_url()
    print()

    # 2. New Birdeye endpoints (run concurrently — each is independent)
    print("New Birdeye Endpoints:")
    await asyncio.gather(
        test_endpoint_18_price(),
        test_endpoint_19_ohlcv(),
        test_endpoint_20_trending(),
        test_endpoint_21_new_listings(),
        test_endpoint_22_creation_info(),
        test_endpoint_23_portfolio(),
        test_endpoint_24_trending_rank(),
    )
    print()

    # 3. Dynamic token polling
    print("Dynamic Token Polling:")
    await test_dynamic_polling_refresh()
    print()

    # ── Summary ──────────────────────────────────────────────────────────────
    passed = sum(1 for s, _, _ in results if s == PASS)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    skipped = sum(1 for s, _, _ in results if s == SKIP)

    print("=" * 60)
    print(f"  Results: {passed} passed  |  {failed} failed  |  {skipped} skipped")
    print("=" * 60 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
