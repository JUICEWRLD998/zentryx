"""
Wallet discovery service.

Calls Birdeye endpoint 1 (gainers-losers) for the week's top performers,
then batches PnL data via endpoint 3 (pnl/multiple) — one batch call
instead of one-per-wallet — filters to the top 15 by win rate + PnL,
stores them in a module-level dict, and upserts them into PostgreSQL.

API call budget per discovery run (down from ~11 → 2 calls):
  1 × get_gainers_losers       — endpoint 1
  1 × get_wallet_pnl_multiple  — endpoint 3 (all addresses in one call)
  ──────────────────────────────────────────────────────────────────
  Total: 2 CU/week  (was ~11 CU with individual pnl/summary calls)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

import db
from db import wallet_table, get_session
from models.schemas import TrackedWallet
from services import birdeye

logger = logging.getLogger(__name__)

# In-memory store — address → TrackedWallet (populated on startup + weekly)
tracked_wallets: dict[str, TrackedWallet] = {}

# Max addresses per pnl/multiple call (Birdeye free-tier safe limit)
_BATCH_SIZE = 10
_INTER_BATCH_DELAY = 2.0  # seconds between batch calls for rate limiting


def _parse_pnl_item(item: dict) -> tuple[float, float, int]:
    """
    Parse (total_pnl, win_rate, trade_count) from a Birdeye PnL item.

    Handles three response shapes:
      1. Flat (pnl/multiple):  item = {"address": ..., "total_pnl": 123, "win_rate": 0.6, ...}
      2. Nested summary (pnl/summary fallback): item = {"pnl": {"realized_profit_usd": ...},
                                                         "counts": {"win_rate": ..., ...}}
      3. Wrapper (pnl/summary): item = {"summary": {"pnl": {...}, "counts": {...}}}
    """
    pnl_field = item.get("pnl")

    # Shape 2: pnl field is a nested dict — item IS the summary block
    if isinstance(pnl_field, dict):
        pnl_block = pnl_field
        counts_block = item.get("counts") or {}
        total_pnl = float(
            pnl_block.get("realized_profit_usd") or pnl_block.get("total_usd") or 0
        )
        win_rate = float(counts_block.get("win_rate") or 0)
        trade_count = int(
            counts_block.get("total_trade") or counts_block.get("total_trading") or 0
        )
        return total_pnl, win_rate, trade_count

    # Shape 1: flat — direct numeric fields
    total_pnl = float(item.get("total_pnl") or pnl_field or item.get("pnl_usd") or 0)
    win_rate = float(item.get("win_rate") or item.get("winRate") or 0)
    trade_count = int(
        item.get("trade_count") or item.get("total_trade") or item.get("total_trading") or 0
    )

    # Shape 3: wrapper — fall through to nested summary block
    if total_pnl == 0 and win_rate == 0:
        summary = item.get("summary") or {}
        pnl_block = summary.get("pnl") or {}
        counts_block = summary.get("counts") or {}
        total_pnl = float(
            pnl_block.get("realized_profit_usd") or pnl_block.get("total_usd") or 0
        )
        win_rate = float(counts_block.get("win_rate") or 0)
        trade_count = int(
            counts_block.get("total_trade") or counts_block.get("total_trading") or 0
        )

    return total_pnl, win_rate, trade_count


async def _fetch_pnl_batch(addresses: list[str]) -> list[tuple[str, dict]]:
    """
    Call /wallet/v2/pnl/multiple for up to _BATCH_SIZE addresses.
    Returns a list of (address, raw_item_dict) pairs.
    Falls back to individual /pnl/summary calls if the batch endpoint fails.
    """
    await asyncio.sleep(_INTER_BATCH_DELAY)
    try:
        raw = await birdeye.get_wallet_pnl_multiple(addresses)
        data = raw.get("data")

        # Response shape: list of items with 'address' field
        if isinstance(data, list):
            return [
                (item.get("address", ""), item)
                for item in data
                if item.get("address")
            ]
        # Response shape: dict keyed by address
        if isinstance(data, dict):
            return [(addr, data[addr]) for addr in addresses if addr in data]

        logger.warning("Unexpected pnl/multiple response shape — falling back to individual calls.")
    except Exception as exc:
        logger.warning("Batch PnL call failed (%s) — falling back to individual calls.", exc)

    # Fallback: individual pnl/summary calls for this batch
    results: list[tuple[str, dict]] = []
    for addr in addresses:
        await asyncio.sleep(1.0)
        try:
            raw = await birdeye.get_wallet_pnl_summary(addr)
            data_block = raw.get("data") or {}
            summary = data_block.get("summary") or {}
            results.append((addr, summary))
        except Exception as e:
            logger.warning("Individual PnL fallback failed for %s: %s", addr[:8], e)
    return results


async def discover_wallets() -> None:
    """
    Refresh the tracked wallet list.

    Steps:
      1. Fetch top 10 weekly gainers (endpoint 1 — API max is 10 per call).
      2. Batch-fetch PnL for all addresses in one call (endpoint 3).
      3. Filter: win_rate >= 0.40 AND total_pnl > 0 AND trade_count >= 5.
      4. Sort by total_pnl desc, keep top 15.
      5. Update in-memory tracked_wallets dict.
      6. Upsert all top 15 into the wallet DB table.
    """
    global tracked_wallets
    logger.info("Starting wallet discovery...")

    try:
        gainers_raw = await birdeye.get_gainers_losers(
            time_frame="1W",
            sort_by="PnL",
            sort_type="desc",
            limit=50,  # capped to 10 by birdeye client (API max per call)
        )
    except Exception as exc:
        logger.error("Failed to fetch gainers-losers: %s", exc)
        return

    data_block = gainers_raw.get("data") or {}
    items = data_block.get("items") or []

    if not items:
        logger.warning("No items returned from gainers-losers endpoint.")
        return

    addresses = [item.get("address") for item in items if item.get("address")]
    logger.info(
        "Fetched %d candidate wallets — batch-fetching PnL data...", len(addresses)
    )

    # ── Batch PnL fetch (replaces N individual pnl/summary calls) ─────────
    batches = [
        addresses[i : i + _BATCH_SIZE] for i in range(0, len(addresses), _BATCH_SIZE)
    ]
    all_results: list[tuple[str, dict]] = []
    for batch in batches:
        batch_results = await _fetch_pnl_batch(batch)
        all_results.extend(batch_results)

    # Build a lookup from gainers response for fallback values
    gainers_lookup = {item.get("address"): item for item in items if item.get("address")}

    # ── Filter & qualify ──────────────────────────────────────────────────
    qualified: list[dict] = []
    for address, raw_item in all_results:
        total_pnl, win_rate, trade_count = _parse_pnl_item(raw_item)

        # If batch returned zero values, try gainers-losers as fallback
        if total_pnl == 0 and win_rate == 0:
            fallback = gainers_lookup.get(address) or {}
            total_pnl = float(
                fallback.get("pnl") or fallback.get("pnl_usd") or 0
            )
            win_rate = float(fallback.get("win_rate") or fallback.get("winRate") or 0)
            trade_count = int(
                fallback.get("trade_count") or fallback.get("total_trading") or 0
            )

        logger.info(
            "Wallet %s — pnl=%.2f win_rate=%.2f trades=%d",
            address[:8], total_pnl, win_rate, trade_count,
        )

        if win_rate >= 0.40 and total_pnl > 0 and trade_count >= 5:
            qualified.append(
                {
                    "address": address,
                    "total_pnl": total_pnl,
                    "win_rate": win_rate,
                    "trade_count": trade_count,
                }
            )

    # Fallback: if nothing passes the filter, seed directly from gainers-losers
    if not qualified:
        logger.warning(
            "No wallets passed PnL filter — seeding %d from gainers-losers.", len(addresses)
        )
        for address in addresses[:15]:
            item = gainers_lookup.get(address, {})
            qualified.append(
                {
                    "address": address,
                    "total_pnl": float(item.get("pnl") or item.get("pnl_usd") or 0),
                    "win_rate": float(item.get("win_rate") or item.get("winRate") or 0),
                    "trade_count": int(
                        item.get("trade_count") or item.get("total_trading") or 0
                    ),
                }
            )

    # ── Sort & take top 15 ────────────────────────────────────────────────
    qualified.sort(key=lambda x: x["total_pnl"], reverse=True)
    top15 = qualified[:15]

    # ── Update in-memory store ────────────────────────────────────────────
    new_wallets: dict[str, TrackedWallet] = {}
    for rank, wallet in enumerate(top15, start=1):
        new_wallets[wallet["address"]] = TrackedWallet(
            address=wallet["address"],
            label=f"Whale #{rank}",
            win_rate=wallet["win_rate"],
            total_pnl=wallet["total_pnl"],
            trade_count=wallet["trade_count"],
        )

    tracked_wallets = new_wallets
    logger.info("Wallet discovery complete — %d wallets tracked.", len(tracked_wallets))

    # ── Persist to PostgreSQL (upsert) ────────────────────────────────────
    if db.is_available():
        upserted = 0
        now = datetime.now(tz=timezone.utc)
        for rank, wallet in enumerate(top15, start=1):
            label = f"Whale #{rank}"
            try:
                stmt = (
                    pg_insert(wallet_table)
                    .values(
                        id=str(uuid.uuid4()),
                        address=wallet["address"],
                        label=label,
                        win_rate=wallet["win_rate"],
                        total_pnl=wallet["total_pnl"],
                        trade_count=wallet["trade_count"],
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["address"],
                        set_={
                            "label": label,
                            "win_rate": wallet["win_rate"],
                            "total_pnl": wallet["total_pnl"],
                            "trade_count": wallet["trade_count"],
                            "updated_at": now,
                        },
                    )
                )
                async with get_session() as session:
                    await session.execute(stmt)
                upserted += 1
            except Exception as exc:
                logger.warning(
                    "DB upsert failed for %s: %s", wallet["address"][:8], exc
                )
        logger.info("Persisted %d/%d wallets to database.", upserted, len(top15))


def get_tracked_wallets() -> list[TrackedWallet]:
    """Return current tracked wallets as a list, ordered by label."""
    return sorted(tracked_wallets.values(), key=lambda w: w.label)

