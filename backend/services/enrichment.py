"""
Alert enrichment pipeline — Phase 4 + DB persistence.

On each incoming REST-poll trade event we:
  1. Pull smart-money token list from a 1-hour DB cache (Birdeye endpoint 13).
  2. Concurrently hit Rugcheck (security/honeypot) and Dex Screener (momentum,
     liquidity, market data) to build a TokenMiniReport — both are free, no API key.
  3. Persist the enriched trade to the trade_event table (deduped by signature).
  4. Broadcast the enriched event to all connected frontend WS clients.
  5. Fire Telegram alerts — shared channel + per-user watchlist DMs.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import db
from db import (
    wallet_table, trade_event_table, user_watchlist_table,
    smart_money_cache_table, token_enrichment_cache_table,
    get_session,
)
from models.schemas import TokenMiniReport
from services import birdeye, dexscreener, rugcheck
from services.ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)

# Module-level lock: prevents concurrent refreshes of the smart-money cache
_smart_money_lock = asyncio.Lock()

# Per-token locks: prevent concurrent enrichment fetches for the same token
_enrichment_locks: dict[str, asyncio.Lock] = {}
_enrichment_locks_mutex = asyncio.Lock()


async def _get_enrichment_lock(token_address: str) -> asyncio.Lock:
    """Return (or lazily create) the per-token lock for enrichment fetches."""
    async with _enrichment_locks_mutex:
        if token_address not in _enrichment_locks:
            _enrichment_locks[token_address] = asyncio.Lock()
        return _enrichment_locks[token_address]



def _report_from_cache(token_address: str, cached, smart_money_flag: bool) -> TokenMiniReport:
    """Build a TokenMiniReport from a SQLAlchemy row (snake_case column names)."""
    return TokenMiniReport(
        token_address=token_address,
        security_score=cached.security_score,
        is_honeypot=cached.is_honeypot,
        smart_money_flag=smart_money_flag,
        momentum_24h=cached.momentum_24h,
        holder_count=cached.holder_count,
        buy_sell_ratio=cached.buy_sell_ratio,
        total_liquidity_usd=cached.liquidity_usd,
        symbol=cached.symbol,
        price=cached.price,
        market_cap=cached.market_cap,
        volume_24h=cached.volume_24h,
    )


async def _get_smart_money_addresses() -> set[str]:
    """
    Return the set of smart-money token addresses.

    Checks the DB SmartMoneyCache table for a non-expired entry first.
    If expired (or absent), fetches from Birdeye endpoint 13, stores to DB
    with expires_at = now + 1 hour, and returns the fresh set.

    Cost: 1 CU per hour maximum (vs 1 CU per trade event before caching).
    """
    if not db.is_available():
        # No DB — fall back to a live call every time
        try:
            raw = await birdeye.get_smart_money_tokens(limit=50)
            items = (raw.get("data") or {}).get("items") or []
            return {item.get("address") for item in items if item.get("address")}
        except Exception:
            return set()

    now = datetime.now(tz=timezone.utc)

    # Fast path: check for a non-expired cache row
    async with get_session() as session:
        result = await session.execute(
            select(smart_money_cache_table)
            .where(smart_money_cache_table.c.expires_at > now)
            .order_by(smart_money_cache_table.c.cached_at.desc())
            .limit(1)
        )
        row = result.fetchone()
    if row:
        return set(row.token_addresses)

    # Slow path (cache miss): fetch from Birdeye under a lock to prevent thundering herd
    async with _smart_money_lock:
        # Re-check after acquiring lock
        async with get_session() as session:
            result = await session.execute(
                select(smart_money_cache_table)
                .where(smart_money_cache_table.c.expires_at > now)
                .order_by(smart_money_cache_table.c.cached_at.desc())
                .limit(1)
            )
            row = result.fetchone()
        if row:
            return set(row.token_addresses)

        try:
            raw = await birdeye.get_smart_money_tokens(limit=50)
            items = (raw.get("data") or {}).get("items") or []
            addresses = [item.get("address") for item in items if item.get("address")]
        except Exception as exc:
            logger.warning("Smart money fetch failed — using empty set: %s", exc)
            addresses = []

        if addresses:
            expires_at = now + timedelta(hours=1)
            try:
                async with get_session() as session:
                    await session.execute(
                        pg_insert(smart_money_cache_table).values(
                            id=str(uuid.uuid4()),
                            token_addresses=addresses,
                            cached_at=now,
                            expires_at=expires_at,
                        )
                    )
                logger.info(
                    "Smart money cache refreshed — %d tokens, expires in 1 hour.",
                    len(addresses),
                )
            except Exception as exc:
                logger.warning("Failed to save smart money cache: %s", exc)

        return set(addresses)


async def build_mini_report(token_address: str) -> TokenMiniReport:
    """
    Build a TokenMiniReport using Rugcheck + Dex Screener, cached 6 hours.

    Data sources:
      - Rugcheck      : security score (0–100), honeypot/rugged detection (free)
      - Dex Screener  : price, 24h momentum, liquidity, volume, buy/sell (free)
      - Birdeye ep 13 : smart-money token list (1-hr DB cache, 1 CU/hr max)

    Cost breakdown:
      - Cache warm (within 6 hrs) → 0 requests  (DB read only)
      - Cache cold (first trade)  → 2 requests  (Rugcheck + DexScreener, then cached)
      - Smart-money flag          → 1 CU/hr max (Birdeye, DB-cached)
    """
    # Smart money is always fresh from its own 1-hour cache
    smart_money_addresses = await _get_smart_money_addresses()
    smart_money_flag = token_address in smart_money_addresses

    # ── Fast path: DB cache hit ──────────────────────────────────────────
    if db.is_available():
        now = datetime.now(tz=timezone.utc)
        async with get_session() as session:
            result = await session.execute(
                select(token_enrichment_cache_table)
                .where(
                    token_enrichment_cache_table.c.token_address == token_address,
                    token_enrichment_cache_table.c.expires_at > now,
                )
                .limit(1)
            )
            cached = result.fetchone()
        if cached:
            logger.debug("Enrichment cache hit for %s", token_address[:8])
            return _report_from_cache(token_address, cached, smart_money_flag)

    # ── Slow path: fetch from Rugcheck + Dex Screener ────────────────────
    token_lock = await _get_enrichment_lock(token_address)
    async with token_lock:
        # Re-check after acquiring lock — another coroutine may have fetched already
        if db.is_available():
            now = datetime.now(tz=timezone.utc)
            async with get_session() as session:
                result = await session.execute(
                    select(token_enrichment_cache_table)
                    .where(
                        token_enrichment_cache_table.c.token_address == token_address,
                        token_enrichment_cache_table.c.expires_at > now,
                    )
                    .limit(1)
                )
                cached = result.fetchone()
            if cached:
                return _report_from_cache(token_address, cached, smart_money_flag)

        logger.debug(
            "Enrichment cache miss — fetching from Rugcheck + DexScreener for %s",
            token_address[:8],
        )

        rugcheck_raw, dex_pair = await asyncio.gather(
            rugcheck.get_token_report(token_address),
            dexscreener.get_token_data(token_address),
        )

        # ── Security score + honeypot (Rugcheck) ────────────────────────
        # score_normalised: 0 = most dangerous, 100 = safest
        security_score: float | None = None
        rc_score = rugcheck_raw.get("score_normalised") if rugcheck_raw else None
        if rc_score is None and rugcheck_raw:
            rc_score = rugcheck_raw.get("score")
        if rc_score is not None:
            try:
                security_score = float(rc_score)
            except (TypeError, ValueError):
                pass

        is_honeypot: bool | None = None
        if rugcheck_raw:
            rugged = rugcheck_raw.get("rugged")
            risks = rugcheck_raw.get("risks") or []
            danger_risks = [r for r in risks if (r.get("level") or "").lower() == "danger"]
            is_honeypot = bool(rugged) or bool(danger_risks)

        # ── Market data (Dex Screener) ───────────────────────────────────
        momentum_24h: float | None = None
        try:
            v = (dex_pair.get("priceChange") or {}).get("h24")
            if v is not None:
                momentum_24h = float(v)
        except (TypeError, ValueError):
            pass

        total_liquidity_usd: float | None = None
        try:
            v = (dex_pair.get("liquidity") or {}).get("usd")
            if v is not None:
                total_liquidity_usd = float(v) or None
        except (TypeError, ValueError):
            pass

        txns_h24 = (dex_pair.get("txns") or {}).get("h24") or {}
        buys = int(txns_h24.get("buys") or 0)
        sells = int(txns_h24.get("sells") or 0)
        total_txns = buys + sells
        buy_sell_ratio: float | None = round(buys / total_txns, 4) if total_txns > 0 else None

        volume_24h: float | None = None
        try:
            v = (dex_pair.get("volume") or {}).get("h24")
            if v is not None:
                volume_24h = float(v) or None
        except (TypeError, ValueError):
            pass

        base_token = dex_pair.get("baseToken") or {}
        symbol: str | None = base_token.get("symbol")

        price: float | None = None
        try:
            v = dex_pair.get("priceUsd")
            if v is not None:
                price = float(v) or None
        except (TypeError, ValueError):
            pass

        market_cap: float | None = None
        try:
            v = dex_pair.get("marketCap") or dex_pair.get("fdv")
            if v is not None:
                market_cap = float(v) or None
        except (TypeError, ValueError):
            pass

        report = TokenMiniReport(
            token_address=token_address,
            security_score=security_score,
            is_honeypot=is_honeypot,
            smart_money_flag=smart_money_flag,
            momentum_24h=momentum_24h,
            holder_count=None,  # not available from Rugcheck summary or DexScreener
            buy_sell_ratio=buy_sell_ratio,
            total_liquidity_usd=total_liquidity_usd,
            symbol=symbol,
            price=price,
            market_cap=market_cap,
            volume_24h=volume_24h,
        )

        # ── Persist to cache ─────────────────────────────────────────────
        if db.is_available():
            expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=6)
            now_ts = datetime.now(tz=timezone.utc)
            try:
                stmt = (
                    pg_insert(token_enrichment_cache_table)
                    .values(
                        id=str(uuid.uuid4()),
                        token_address=token_address,
                        cached_at=now_ts,
                        expires_at=expires_at,
                        security_score=report.security_score,
                        is_honeypot=report.is_honeypot,
                        momentum_24h=report.momentum_24h,
                        holder_count=report.holder_count,
                        buy_sell_ratio=report.buy_sell_ratio,
                        liquidity_usd=report.total_liquidity_usd,
                        symbol=report.symbol,
                        price=report.price,
                        market_cap=report.market_cap,
                        volume_24h=report.volume_24h,
                    )
                    .on_conflict_do_update(
                        index_elements=["token_address"],
                        set_={
                            "expires_at": expires_at,
                            "security_score": report.security_score,
                            "is_honeypot": report.is_honeypot,
                            "momentum_24h": report.momentum_24h,
                            "holder_count": report.holder_count,
                            "buy_sell_ratio": report.buy_sell_ratio,
                            "liquidity_usd": report.total_liquidity_usd,
                            "symbol": report.symbol,
                            "price": report.price,
                            "market_cap": report.market_cap,
                            "volume_24h": report.volume_24h,
                        },
                    )
                )
                async with get_session() as session:
                    await session.execute(stmt)
                logger.info(
                    "Enrichment cache stored for %s (%s) — expires in 6 hours.",
                    token_address[:8], report.symbol or "?",
                )
            except Exception as exc:
                logger.warning("Failed to store enrichment cache: %s", exc)

        return report


async def _persist_trade(
    *,
    signature: str,
    wallet_address: str | None,
    wallet_label: str | None,
    token_address: str,
    token_symbol: str | None,
    side: str,
    usd_value: float,
    block_time: int | None,
    report: TokenMiniReport,
) -> None:
    """
    Upsert a TradeEvent row into PostgreSQL.
    Uses signature as the unique key — duplicate txs are silently ignored.
    """
    if not db.is_available() or not signature:
        return

    side_str = side.upper()
    if side_str not in ("BUY", "SELL"):
        side_str = "UNKNOWN"

    ts = (
        datetime.fromtimestamp(block_time, tz=timezone.utc)
        if block_time
        else datetime.now(tz=timezone.utc)
    )

    # Resolve DB wallet FK (nullable — anonymous large trades have no wallet row)
    wallet_id: str | None = None
    if wallet_address:
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(wallet_table).where(wallet_table.c.address == wallet_address)
                )
                row = result.fetchone()
            if row:
                wallet_id = row.id
        except Exception as exc:
            logger.debug("Wallet FK lookup failed for %s: %s", wallet_address[:8], exc)

    try:
        stmt = (
            pg_insert(trade_event_table)
            .values(
                id=str(uuid.uuid4()),
                signature=signature,
                wallet_id=wallet_id,
                wallet_label=wallet_label,
                token_address=token_address,
                token_symbol=token_symbol,
                side=side_str,
                usd_value=usd_value,
                timestamp=ts,
                security_score=report.security_score,
                is_honeypot=report.is_honeypot,
                smart_money_flag=report.smart_money_flag,
                momentum_24h=report.momentum_24h,
                holder_count=report.holder_count,
                buy_sell_ratio=report.buy_sell_ratio,
                liquidity_usd=report.total_liquidity_usd,
                alert_sent=False,
                created_at=datetime.now(tz=timezone.utc),
            )
            .on_conflict_do_nothing(index_elements=["signature"])
        )
        async with get_session() as session:
            await session.execute(stmt)
    except Exception as exc:
        logger.warning("Trade persistence failed for %s: %s", signature[:16], exc)


async def _send_watchlist_alerts(
    wallet_id: str | None,
    wallet_label: str,
    wallet_address: str,
    token_symbol: str,
    token_address: str,
    side: str,
    usd_value: float,
    report: TokenMiniReport,
) -> None:
    """
    Send personal DM alerts to Telegram users who are watching this wallet.
    Requires the user to have previously /start-ed the bot (opened a DM).
    """
    if not db.is_available() or not wallet_id:
        return

    from services.telegram import send_personal_trade_alert  # avoid circular import

    try:
        async with get_session() as session:
            result = await session.execute(
                select(user_watchlist_table)
                .where(user_watchlist_table.c.wallet_id == wallet_id)
            )
            watchers = result.fetchall()
    except Exception as exc:
        logger.debug("Watchlist query failed: %s", exc)
        return

    for watcher in watchers:
        asyncio.create_task(
            send_personal_trade_alert(
                telegram_user_id=int(watcher.telegram_user_id),
                wallet_label=wallet_label,
                wallet_address=wallet_address,
                token_symbol=token_symbol,
                token_address=token_address,
                side=side,
                usd_value=usd_value,
                security_score=report.security_score,
                smart_money=report.smart_money_flag,
                momentum_24h=report.momentum_24h,
            )
        )


async def process_trade_event(raw_event: dict[str, Any]) -> None:
    """
    Called for every incoming REST-poll trade event.
    1. Validate it's a trade we care about.
    2. Enrich with TokenMiniReport (smart money from DB cache).
    3. Persist to trade_event table (deduped by signature).
    4. Broadcast enriched event to all WS frontend clients.
    5. Fire Telegram alerts (shared channel + per-user watchlist DMs).
    """
    from services.telegram import send_trade_alert
    from services.wallet_discovery import tracked_wallets

    event_type = raw_event.get("type", "")
    data = raw_event.get("data") or {}

    if event_type not in ("WALLET_TXS", "LARGE_TRADE_TXS"):
        return

    token_address = data.get("token_address") or data.get("tokenAddress") or data.get("mint")
    wallet_address = data.get("wallet") or data.get("owner")
    usd_value = data.get("value_usd") or data.get("valueUsd") or data.get("volumeUSD") or data.get("volume")
    side = data.get("side") or ("buy" if data.get("type") == "BUY" else "sell")
    tx_hash = data.get("tx_hash") or data.get("txHash") or data.get("signature")
    block_time = data.get("block_time") or data.get("blockTime") or data.get("blockUnixTime")

    if not token_address:
        return

    wallet_label: str | None = None
    if wallet_address and wallet_address in tracked_wallets:
        wallet_label = tracked_wallets[wallet_address].label
    elif data.get("wallet_label"):          # label already resolved by RPC/polling layer
        wallet_label = data["wallet_label"]
    elif event_type == "LARGE_TRADE_TXS":
        wallet_label = "Whale Alert"        # fallback when no label was pre-resolved

    if wallet_label is None:
        return

    logger.info(
        "Processing trade: %s | %s | $%s | %s",
        wallet_label, side.upper(), usd_value, token_address[:8],
    )

    # ── Enrich ────────────────────────────────────────────────────────────
    try:
        mini_report = await build_mini_report(token_address)
    except Exception as exc:
        logger.warning("Enrichment failed for %s: %s", token_address, exc)
        mini_report = TokenMiniReport(token_address=token_address)

    # ── Persist trade to DB ───────────────────────────────────────────────
    wallet_id: str | None = None
    if tx_hash:
        await _persist_trade(
            signature=tx_hash,
            wallet_address=wallet_address,
            wallet_label=wallet_label,
            token_address=token_address,
            token_symbol=mini_report.symbol,
            side=side.upper(),
            usd_value=float(usd_value or 0),
            block_time=block_time,
            report=mini_report,
        )
        # Resolve wallet_id for watchlist alerts
        if db.is_available() and wallet_address:
            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(wallet_table).where(wallet_table.c.address == wallet_address)
                    )
                    db_wallet = result.fetchone()
                if db_wallet:
                    wallet_id = db_wallet.id
            except Exception:
                pass

    # ── Broadcast to frontend WS clients ─────────────────────────────────
    broadcast_payload = {
        "type": event_type,
        "wallet_address": wallet_address,
        "wallet_label": wallet_label,
        "token_address": token_address,
        "symbol": mini_report.symbol,
        "side": side.upper(),
        "usd_value": usd_value,
        "tx_hash": tx_hash,
        "block_time": block_time,
        "mini_report": mini_report.model_dump(),
    }
    await ws_manager.broadcast(broadcast_payload)

    # ── Telegram: shared channel alert ───────────────────────────────────
    asyncio.create_task(
        send_trade_alert(
            wallet_label=wallet_label,
            wallet_address=wallet_address or "",
            token_symbol=mini_report.symbol or token_address[:8],
            token_address=token_address,
            side=side.upper(),
            usd_value=float(usd_value or 0),
            security_score=mini_report.security_score,
            smart_money=mini_report.smart_money_flag,
            momentum_24h=mini_report.momentum_24h,
        )
    )

    # ── Telegram: per-user watchlist DMs ─────────────────────────────────
    asyncio.create_task(
        _send_watchlist_alerts(
            wallet_id=wallet_id,
            wallet_label=wallet_label,
            wallet_address=wallet_address or "",
            token_symbol=mini_report.symbol or token_address[:8],
            token_address=token_address,
            side=side.upper(),
            usd_value=float(usd_value or 0),
            report=mini_report,
        )
    )
