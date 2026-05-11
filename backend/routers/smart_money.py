"""
Smart money signal router.

GET /api/smart-money/heatmap
  — Fetches the top smart money tokens from Birdeye's free smart-money token
    list endpoint and computes a BUY / SELL / NEUTRAL signal from the buy/sell
    volume fields returned by that endpoint.
  — The premium inflow/outflow endpoint is NOT used (returns 404 on free tier).
  — Results are cached in-process for 15 minutes.

Response schema:
  {
    "tokens": [
      {
        "address": str,
        "symbol": str,
        "name": str,
        "logo_uri": str,
        "signal": "BUY" | "SELL" | "NEUTRAL",
        "buy_usd": float,
        "sell_usd": float,
        "net_usd": float
      },
      ...
    ],
    "generated_at": int   # unix timestamp
  }
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from services import birdeye

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/smart-money", tags=["smart-money"])

# In-process cache: (result, expires_at_unix)
_cache: tuple[dict[str, Any], float] | None = None
_CACHE_TTL = 900  # 15 minutes


def _compute_signal(item: dict[str, Any]) -> tuple[str, float, float, float]:
    """
    Derive BUY / SELL / NEUTRAL signal from a smart-money token list item.

    Birdeye's /smart-money/v1/token/list items may include buy/sell volume
    fields under several naming conventions — try them all.

    If no buy/sell data is present the token is still on the smart-money list,
    which itself indicates smart-money accumulation, so we default to BUY.
    """
    buy = float(
        item.get("buy") or item.get("buyVolume") or item.get("buyAmountUsd") or 0
    )
    sell = float(
        item.get("sell") or item.get("sellVolume") or item.get("sellAmountUsd") or 0
    )
    # Prefer an explicit net field; fall back to computing it.
    net_raw = item.get("net") or item.get("netBuy") or item.get("net_buy")
    net = float(net_raw) if net_raw is not None else (buy - sell)

    if buy == 0 and sell == 0:
        # No volume data — token is on the smart-money list → accumulating.
        return "BUY", 0.0, 0.0, 0.0

    if net > 0:
        return "BUY", buy, sell, net
    if net < 0:
        return "SELL", buy, sell, net
    return "NEUTRAL", buy, sell, net


async def _build_heatmap(limit: int = 20) -> dict[str, Any]:
    """Fetch the smart money token list and derive per-token signals."""
    try:
        raw_list = await birdeye.get_smart_money_tokens(limit=limit)
    except Exception as exc:
        logger.error("Failed to fetch smart money token list: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream Birdeye error") from exc

    # API may return {"data": [...]} or {"data": {"items": [...]}}
    raw_data = raw_list.get("data") if isinstance(raw_list, dict) else raw_list
    if isinstance(raw_data, dict):
        items = raw_data.get("items") or []
    elif isinstance(raw_data, list):
        items = raw_data
    else:
        items = []

    if not items:
        return {"tokens": [], "generated_at": int(time.time())}

    tokens: list[dict[str, Any]] = []
    for item in items:
        addr = item.get("token") or item.get("address", "")
        if not addr:
            continue
        signal, buy_usd, sell_usd, net_usd = _compute_signal(item)
        tokens.append(
            {
                "address": addr,
                "symbol": item.get("symbol", ""),
                "name": item.get("name", ""),
                "logo_uri": (
                    item.get("logo_uri")
                    or item.get("logoURI")
                    or item.get("logoUri")
                    or ""
                ),
                "signal": signal,
                "buy_usd": round(buy_usd, 2),
                "sell_usd": round(sell_usd, 2),
                "net_usd": round(net_usd, 2),
            }
        )

    return {"tokens": tokens, "generated_at": int(time.time())}


# ── Heatmap ───────────────────────────────────────────────────────────────────

@router.get("/heatmap")
async def get_smart_money_heatmap(limit: int = 20) -> dict[str, Any]:
    """Return smart money inflow/outflow heatmap for top tokens.

    Query params:
      limit: number of tokens (1–50, default 20)

    Cached for 15 minutes.
    """
    global _cache

    # Validate limit
    limit = max(1, min(50, limit))

    # Return cached result if fresh
    now = time.time()
    if _cache is not None:
        result, expires_at = _cache
        if now < expires_at:
            return result

    # Build fresh data
    data = await _build_heatmap(limit=limit)
    _cache = (data, now + _CACHE_TTL)
    return data
