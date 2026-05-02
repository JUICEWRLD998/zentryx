"""
Dex Screener client — free, no API key required.

Endpoint: GET https://api.dexscreener.com/latest/dex/tokens/{address}

Returns all trading pairs for a Solana token. We pick the pair with the
highest liquidity USD as the most representative market data source.

Used to populate momentum_24h, total_liquidity_usd, volume_24h,
buy_sell_ratio, symbol, price, and market_cap in TokenMiniReport.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dexscreener.com"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"accept": "application/json"},
            timeout=15.0,
        )
    return _client


def _best_pair(pairs: list[dict]) -> dict[str, Any]:
    """Return the pair with the highest liquidity USD, or {} if the list is empty."""
    if not pairs:
        return {}
    return max(
        pairs,
        key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
    )


async def get_token_data(address: str) -> dict[str, Any]:
    """
    Fetch all DEX trading pairs for a Solana token and return the one with
    the highest liquidity (most representative price / volume source).

    Relevant fields in the returned dict:
      baseToken.symbol      — token ticker
      priceUsd              — current price (str)
      priceChange.h24       — 24h price change %
      liquidity.usd         — total liquidity USD
      volume.h24            — 24h volume USD
      txns.h24.buys         — number of buy transactions in last 24h
      txns.h24.sells        — number of sell transactions in last 24h
      marketCap / fdv       — market cap or fully diluted valuation

    Returns {} on any error or when no pairs exist.
    """
    client = _get_client()
    try:
        response = await client.get(f"/latest/dex/tokens/{address}")
        response.raise_for_status()
        data = response.json()
        return _best_pair(data.get("pairs") or [])
    except httpx.HTTPStatusError as exc:
        logger.debug(
            "DexScreener HTTP %s for %s: %s",
            exc.response.status_code, address[:8], exc.response.text[:200],
        )
        return {}
    except Exception as exc:
        logger.debug("DexScreener request failed for %s: %s", address[:8], exc)
        return {}
