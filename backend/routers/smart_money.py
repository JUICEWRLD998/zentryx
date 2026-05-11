"""
Smart money inflow/outflow heatmap router.

GET /api/smart-money/heatmap
  — Fetches the top smart money tokens, then queries inflow/outflow for each
    across three time windows (1H, 4H, 24H).
  — Results are cached in-process for 15 minutes to avoid hammering the API.

Response schema:
  {
    "tokens": [
      {
        "address": str,
        "symbol": str,
        "name": str,
        "logo_uri": str,
        "1h":  { "inflow": float, "outflow": float, "net": float },
        "4h":  { "inflow": float, "outflow": float, "net": float },
        "24h": { "inflow": float, "outflow": float, "net": float }
      },
      ...
    ],
    "generated_at": int   # unix timestamp
  }
"""
from __future__ import annotations

import asyncio
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


def _parse_flow(raw: dict[str, Any]) -> dict[str, float]:
    """Extract inflow, outflow, net from a single Birdeye inflow-outflow response."""
    data = raw.get("data") or {}
    inflow = float(data.get("buyAmount") or data.get("inflow") or 0)
    outflow = float(data.get("sellAmount") or data.get("outflow") or 0)
    net = inflow - outflow
    return {"inflow": inflow, "outflow": outflow, "net": net}


async def _fetch_flows_for_token(
    address: str,
) -> dict[str, dict[str, float]]:
    """Fetch 1H / 4H / 24H flows for a single token. Returns zeros on error."""
    frames = ["1H", "4H", "24H"]

    async def _safe_fetch(frame: str) -> dict[str, float]:
        try:
            raw = await birdeye.get_smart_money_inflow_outflow(address, time_frame=frame)
            return _parse_flow(raw)
        except Exception as exc:
            logger.debug("Flow fetch failed for %s@%s: %s", address, frame, exc)
            return {"inflow": 0.0, "outflow": 0.0, "net": 0.0}

    results = await asyncio.gather(*[_safe_fetch(f) for f in frames])
    return {"1h": results[0], "4h": results[1], "24h": results[2]}


async def _build_heatmap(limit: int = 20) -> dict[str, Any]:
    """Core builder — fetch token list then flows in parallel."""
    # Step 1: get top smart money tokens
    try:
        raw_list = await birdeye.get_smart_money_tokens(limit=limit)
    except Exception as exc:
        logger.error("Failed to fetch smart money token list: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream Birdeye error") from exc

    # API returns {"data": [...]} where data is a bare list of token objects.
    # The token address field is "token" (not "address").
    raw_data = raw_list.get("data") if isinstance(raw_list, dict) else raw_list
    if isinstance(raw_data, dict):
        # Older nested shape: {"data": {"items": [...]}}
        items = raw_data.get("items") or []
    elif isinstance(raw_data, list):
        items = raw_data
    else:
        items = []
    if not items:
        return {"tokens": [], "generated_at": int(time.time())}

    # Step 2: fetch flows for every token concurrently (3 frames each)
    # The address field is named "token" in the smart-money API response
    addresses = [item.get("token") or item.get("address", "") for item in items]
    addresses = [a for a in addresses if a]

    flow_results = await asyncio.gather(
        *[_fetch_flows_for_token(addr) for addr in addresses]
    )

    # Step 3: merge
    tokens = []
    for item, flows in zip(items, flow_results):
        addr = item.get("token") or item.get("address", "")
        tokens.append(
            {
                "address": addr,
                "symbol": item.get("symbol", ""),
                "name": item.get("name", ""),
                "logo_uri": item.get("logo_uri") or item.get("logoURI") or "",
                "1h": flows["1h"],
                "4h": flows["4h"],
                "24h": flows["24h"],
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
