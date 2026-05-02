"""
Rugcheck client — free, no API key required.

Endpoint: GET https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary

Returns a security report for any Solana token:
  - score_normalised  : 0–100, higher = safer
  - risks             : list of {name, description, level (info/warn/danger)}
  - rugged            : bool — true if the token has already been rug-pulled

Used to populate security_score and is_honeypot in TokenMiniReport.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.rugcheck.xyz"

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


async def get_token_report(mint: str) -> dict[str, Any]:
    """
    Fetch the summary security report for a Solana token mint address.

    Returns a dict with at minimum:
      score_normalised (float 0–100), risks (list), rugged (bool)

    Returns {} on any error so callers can treat missing data as None.
    """
    client = _get_client()
    try:
        response = await client.get(f"/v1/tokens/{mint}/report/summary")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.debug(
            "Rugcheck HTTP %s for %s: %s",
            exc.response.status_code, mint[:8], exc.response.text[:200],
        )
        return {}
    except Exception as exc:
        logger.debug("Rugcheck request failed for %s: %s", mint[:8], exc)
        return {}
