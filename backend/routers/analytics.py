"""
Analytics router — Phase 4 (Signal Profitability) + Phase 5 (Whale Rotations).

GET /api/signals/stats  — pre-computed signal win-rate & top performers
GET /api/rotations      — recent whale rotation events (SELL A → BUY B)
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analytics"])

# ── Phase 4: Signal Profitability ─────────────────────────────────────────────

@router.get("/signals/stats")
async def get_signal_stats() -> dict[str, Any]:
    """
    Return pre-computed signal profitability stats from signal_stats.py.

    The computation runs every 2 hours via APScheduler.  Returns the last
    cached result immediately; if the cache is cold (backend just started),
    returns a zeroed payload rather than a 503.

    Response:
    {
      "computed_at": str | null,    # ISO datetime of last run
      "total_signals": int,
      "profitable": int,
      "win_rate": float,            # percentage, e.g. 62.5
      "avg_return_pct": float,
      "top_performers": [
        { "address": str, "symbol": str, "entry_usd": float,
          "current_price": float, "return_pct": float }
      ]
    }
    """
    from services.signal_stats import get_cached_stats

    stats = get_cached_stats()
    if stats is None:
        return {
            "computed_at": None,
            "total_signals": 0,
            "profitable": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "top_performers": [],
        }
    return stats


# ── Phase 5: Whale Rotation Detector ─────────────────────────────────────────

_rotations_cache: tuple[list, float] | None = None
_ROTATIONS_CACHE_TTL = 300  # 5 minutes


@router.get("/rotations")
async def get_rotations(limit: int = 10) -> dict[str, Any]:
    """
    Return the most recent whale rotation events.

    A *rotation* is detected when the same tracked whale wallet SELLs token A
    and BUYs token B (a different token) within a 4-hour window.

    Query params:
      limit: max rotations to return (1–50, default 10)

    Response:
    {
      "rotations": [
        {
          "wallet_label": str,
          "from_token":   str,
          "from_symbol":  str,
          "to_token":     str,
          "to_symbol":    str,
          "from_usd":     float,
          "to_usd":       float,
          "detected_at":  str    # ISO 8601 datetime
        }
      ],
      "generated_at": int        # unix timestamp of this response
    }

    Cached 5 minutes.
    """
    global _rotations_cache

    limit = max(1, min(50, limit))
    now = time.time()

    if _rotations_cache is not None:
        result, expires_at = _rotations_cache
        if now < expires_at:
            return {"rotations": result, "generated_at": int(now)}

    from services.rotation_detector import detect_rotations

    rotations = await detect_rotations(limit=limit)
    _rotations_cache = (rotations, now + _ROTATIONS_CACHE_TTL)
    return {"rotations": rotations, "generated_at": int(now)}
