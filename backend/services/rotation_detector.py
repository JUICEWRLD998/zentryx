"""
Whale Rotation Detector — Phase 5.

Detects when a tracked whale SELLs token A and then BUYs token B
(a different token) by the same wallet within a configurable time window
(default: 4 hours).

No new DB tables required — reads from the existing trade_event_table.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# How long after a SELL to look for a matching BUY (same wallet, different token)
ROTATION_WINDOW_HOURS: int = 4

# How far back in time to scan for candidate trades
LOOKBACK_HOURS: int = 48


async def detect_rotations(limit: int = 10) -> list[dict[str, Any]]:
    """
    Scan trade_event_table for SELL→BUY pairs by the same wallet within
    ROTATION_WINDOW_HOURS on *different* tokens.

    Returns up to `limit` most-recent unique rotations, sorted newest-first.

    A rotation is deduplicated by (wallet_label, from_token, to_token) —
    only the most recent instance of each pair is kept.
    """
    import db

    if not db.is_available():
        logger.debug("rotation_detector: DB unavailable, returning empty list")
        return []

    from db import trade_event_table, get_session
    from sqlalchemy import select

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    try:
        async with get_session() as session:
            from services.wallet_discovery import tracked_wallets
            tracked_labels = {tw.label for tw in tracked_wallets.values()}

            result = await session.execute(
                select(
                    trade_event_table.c.wallet_label,
                    trade_event_table.c.wallet_id,
                    trade_event_table.c.token_address,
                    trade_event_table.c.token_symbol,
                    trade_event_table.c.side,
                    trade_event_table.c.usd_value,
                    trade_event_table.c.timestamp,
                )
                .where(
                    trade_event_table.c.timestamp >= cutoff,
                    trade_event_table.c.wallet_label.in_(list(tracked_labels)) if tracked_labels else False,
                )
                .order_by(trade_event_table.c.timestamp.asc())
            )
            rows = result.fetchall()
    except Exception as exc:
        logger.error("rotation_detector: DB query failed: %s", exc)
        return []

    if not rows:
        return []

    return _compute_rotations(rows, limit)


def _compute_rotations(rows: list, limit: int) -> list[dict[str, Any]]:
    """
    Pure algorithmic core — separated from DB I/O so it can be unit-tested
    without a live database.

    Args:
        rows: iterable of trade_event rows with attributes:
              wallet_label, wallet_id, token_address, token_symbol,
              side, usd_value, timestamp
        limit: max unique rotations to return

    Returns:
        List of rotation dicts sorted newest-first.
    """
    # Group events by wallet identity
    by_wallet: dict[str, list] = defaultdict(list)
    for row in rows:
        key = row.wallet_label or row.wallet_id or "Unknown"
        by_wallet[key].append(row)

    window_secs = ROTATION_WINDOW_HOURS * 3600
    rotations: list[dict[str, Any]] = []

    for wallet_label, events in by_wallet.items():
        sells = [e for e in events if e.side == "SELL"]
        buys = [e for e in events if e.side == "BUY"]

        for sell in sells:
            for buy in buys:
                # Must be a different token
                if buy.token_address == sell.token_address:
                    continue
                # BUY must occur strictly after the SELL, within the window
                delta = (buy.timestamp - sell.timestamp).total_seconds()
                if 0 < delta <= window_secs:
                    rotations.append(
                        {
                            "wallet_label": wallet_label,
                            "from_token": sell.token_address,
                            "from_symbol": sell.token_symbol or sell.token_address[:8],
                            "to_token": buy.token_address,
                            "to_symbol": buy.token_symbol or buy.token_address[:8],
                            "from_usd": round(float(sell.usd_value or 0), 2),
                            "to_usd": round(float(buy.usd_value or 0), 2),
                            "detected_at": buy.timestamp.isoformat(),
                        }
                    )

    # Sort newest-first
    rotations.sort(key=lambda x: x["detected_at"], reverse=True)

    # Deduplicate: keep only the most recent instance of each
    # (wallet_label, from_token, to_token) triple
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for r in rotations:
        key: tuple[str, str, str] = (r["wallet_label"], r["from_token"], r["to_token"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique[:limit]
