"""
Birdeye REST client — all 17 endpoints as async typed methods.

Uses a module-level httpx.AsyncClient with exponential backoff retry.
The client is initialized lazily on first call so it picks up env vars
after dotenv has loaded them.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://public-api.birdeye.so"
DEFAULT_CHAIN = "solana"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        api_key = os.getenv("BIRDEYE_API_KEY", "")
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "X-API-KEY": api_key,
                "x-chain": DEFAULT_CHAIN,
                "accept": "application/json",
            },
            timeout=30.0,
        )
    return _client


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET with exponential backoff retry (max 3 attempts: 1s, 2s, 4s)."""
    client = _get_client()
    delays = [1, 2, 4]
    last_exc: Exception | None = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            # Don't retry on 4xx client errors (bad params, auth, etc.)
            if 400 <= exc.response.status_code < 500:
                logger.error("Birdeye 4xx %s %s: %s", exc.response.status_code, path, exc.response.text)
                raise
            last_exc = exc
            logger.warning("Birdeye attempt %d/%d failed (%s): %s", attempt, len(delays), path, exc)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            last_exc = exc
            logger.warning("Birdeye attempt %d/%d network error (%s): %s", attempt, len(delays), path, exc)

        if attempt < len(delays):
            await asyncio.sleep(delay)

    raise RuntimeError(f"Birdeye request failed after {len(delays)} attempts: {path}") from last_exc


# ---------------------------------------------------------------------------
# 1. Trader / Wallet endpoints
# ---------------------------------------------------------------------------

async def get_gainers_losers(
    time_frame: str = "1W",
    sort_by: str = "PnL",
    sort_type: str = "desc",
    offset: int = 0,
    limit: int = 10,
) -> dict[str, Any]:
    """Endpoint 1 — /trader/gainers-losers (limit max 10)"""
    return await _get(
        "/trader/gainers-losers",
        params={
            "type": time_frame,
            "sort_by": sort_by,
            "sort_type": sort_type,
            "offset": offset,
            "limit": min(limit, 10),  # API max is 10
        },
    )


async def get_wallet_pnl_summary(wallet: str, token: str | None = None) -> dict[str, Any]:
    """Endpoint 2 — /wallet/v2/pnl/summary"""
    params: dict[str, Any] = {"wallet": wallet}
    if token:
        params["token"] = token
    return await _get("/wallet/v2/pnl/summary", params=params)


async def get_wallet_pnl_multiple(wallet_list: list[str]) -> dict[str, Any]:
    """Endpoint 3 — /wallet/v2/pnl/multiple"""
    return await _get(
        "/wallet/v2/pnl/multiple",
        params={"list_address": ",".join(wallet_list)},
    )


async def get_wallet_net_worth_details(wallet: str) -> dict[str, Any]:
    """Endpoint 4 — /wallet/v2/net-worth-details"""
    return await _get("/wallet/v2/net-worth-details", params={"wallet": wallet})


async def get_wallet_net_worth(wallet: str) -> dict[str, Any]:
    """Endpoint 5 — /wallet/v2/net-worth"""
    return await _get("/wallet/v2/net-worth", params={"wallet": wallet})


async def get_wallet_balance_change(wallet: str) -> dict[str, Any]:
    """Endpoint 6 — /wallet/v2/balance-change"""
    return await _get("/wallet/v2/balance-change", params={"wallet": wallet})


async def get_wallet_tx_list(
    wallet: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Endpoint 7 — /v1/wallet/tx_list"""
    return await _get(
        "/v1/wallet/tx_list",
        params={"wallet": wallet, "limit": limit, "offset": offset},
    )


# ---------------------------------------------------------------------------
# 2. Token intelligence endpoints
# ---------------------------------------------------------------------------

async def get_top_traders(token_address: str, limit: int = 20) -> dict[str, Any]:
    """Endpoint 8 — /defi/v2/tokens/top_traders"""
    return await _get(
        "/defi/v2/tokens/top_traders",
        params={"address": token_address, "limit": limit},
    )


async def get_token_security(token_address: str) -> dict[str, Any]:
    """Endpoint 9 — /defi/token_security"""
    return await _get("/defi/token_security", params={"address": token_address})


async def get_price_stats(token_address: str) -> dict[str, Any]:
    """Endpoint 10 — /defi/v3/price-stats/single"""
    return await _get("/defi/v3/price-stats/single", params={"address": token_address})


async def get_token_holders(token_address: str) -> dict[str, Any]:
    """Endpoint 11 — /defi/v3/token/holder"""
    return await _get("/defi/v3/token/holder", params={"address": token_address})


async def get_holder_distribution(token_address: str) -> dict[str, Any]:
    """Endpoint 12 — /holder/v1/distribution"""
    return await _get("/holder/v1/distribution", params={"address": token_address})


async def get_smart_money_tokens(limit: int = 50) -> dict[str, Any]:
    """Endpoint 13 — /smart-money/v1/token/list"""
    return await _get("/smart-money/v1/token/list", params={"limit": limit})


async def get_token_overview(token_address: str) -> dict[str, Any]:
    """Endpoint 14 — /defi/token_overview"""
    return await _get("/defi/token_overview", params={"address": token_address})


async def get_token_trade_data(token_address: str) -> dict[str, Any]:
    """Endpoint 15 — /defi/v3/token/trade-data/single"""
    return await _get("/defi/v3/token/trade-data/single", params={"address": token_address})


async def get_token_txs(
    token_address: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Endpoint 16 — /defi/v3/token/txs"""
    return await _get(
        "/defi/v3/token/txs",
        params={"address": token_address, "limit": limit, "offset": offset},
    )


async def get_exit_liquidity(token_address: str) -> dict[str, Any]:
    """Endpoint 17 — /defi/v3/token/exit-liquidity"""
    return await _get("/defi/v3/token/exit-liquidity", params={"address": token_address})
