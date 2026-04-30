"""
Alert enrichment pipeline — Phase 4 + DB persistence.

On each incoming REST-poll trade event we:
  1. Pull smart-money token list from a 1-hour DB cache (saves ~9 CU/hr).
  2. Concurrently hit token-intelligence endpoints 9–17 (minus endpoint 13
     which is now cached) to build a TokenMiniReport.
  3. Persist the enriched trade to the trade_event table (deduped by signature).
  4. Broadcast the enriched event to all connected frontend WS clients.
  5. Fire Telegram alerts — shared channel + per-user watchlist DMs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import db
from models.schemas import TokenMiniReport
from services import birdeye
from services.ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)

# Module-level lock: prevents concurrent refreshes of the smart-money cache
_smart_money_lock = asyncio.Lock()

# Per-token locks: prevent concurrent Birdeye fetches for the same token
_enrichment_locks: dict[str, asyncio.Lock] = {}
_enrichment_locks_mutex = asyncio.Lock()


async def _get_enrichment_lock(token_address: str) -> asyncio.Lock:
    """Return (or lazily create) the per-token lock for enrichment fetches."""
    async with _enrichment_locks_mutex:
        if token_address not in _enrichment_locks:
            _enrichment_locks[token_address] = asyncio.Lock()
        return _enrichment_locks[token_address]


def _report_from_cache(token_address: str, cached, smart_money_flag: bool) -> TokenMiniReport:
    """Build a TokenMiniReport directly from a TokenEnrichmentCache DB row."""
    return TokenMiniReport(
        token_address=token_address,
        security_score=cached.securityScore,
        is_honeypot=cached.isHoneypot,
        smart_money_flag=smart_money_flag,
        momentum_24h=cached.momentum24h,
        holder_count=cached.holderCount,
        buy_sell_ratio=cached.buySellRatio,
        total_liquidity_usd=cached.liquidityUsd,
        symbol=cached.symbol,
        price=cached.price,
        market_cap=cached.marketCap,
        volume_24h=cached.volume24h,
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
    cache = await db.prisma.smartmoneycache.find_first(
        where={"expiresAt": {"gt": now}},
        order={"cachedAt": "desc"},
    )
    if cache:
        return set(cache.tokenAddresses)

    # Slow path (cache miss): fetch from Birdeye under a lock to prevent thundering herd
    async with _smart_money_lock:
        # Re-check after acquiring lock (another coroutine may have refreshed already)
        cache = await db.prisma.smartmoneycache.find_first(
            where={"expiresAt": {"gt": now}},
            order={"cachedAt": "desc"},
        )
        if cache:
            return set(cache.tokenAddresses)

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
                await db.prisma.smartmoneycache.create(
                    data={"tokenAddresses": addresses, "expiresAt": expires_at}
                )
                logger.info(
                    "Smart money cache refreshed — %d tokens, expires in 1 hour.",
                    len(addresses),
                )
            except Exception as exc:
                logger.warning("Failed to save smart money cache: %s", exc)

        return set(addresses)


async def _safe(coro) -> dict[str, Any]:
    """Run a coroutine and return its result dict, or {} on any error."""
    try:
        return await coro
    except Exception as exc:
        logger.debug("Enrichment sub-call failed: %s", exc)
        return {}


async def build_mini_report(token_address: str) -> TokenMiniReport:
    """
    Build a TokenMiniReport, caching all 8 Birdeye endpoint results per token
    for 6 hours in the TokenEnrichmentCache table.

    Cost breakdown:
      - Cache warm (within 6 hrs) → 0 CU  (DB read only)
      - Cache cold (first trade)  → 8 CU  (Birdeye fetch, then cached 6 hrs)
      - Smart-money flag          → 0 CU  (resolved via SmartMoneyCache, 1-hr TTL)
    """
    # Smart money is always fresh from its own 1-hour cache (0 CU if warm)
    smart_money_addresses = await _get_smart_money_addresses()
    smart_money_flag = token_address in smart_money_addresses

    # ── Fast path: DB cache hit ──────────────────────────────────────────
    if db.is_available():
        now = datetime.now(tz=timezone.utc)
        cached = await db.prisma.tokenenrichmentcache.find_first(
            where={"tokenAddress": token_address, "expiresAt": {"gt": now}},
        )
        if cached:
            logger.debug("Enrichment cache hit for %s", token_address[:8])
            return _report_from_cache(token_address, cached, smart_money_flag)

    # ── Slow path: fetch from Birdeye under a per-token lock ─────────────
    token_lock = await _get_enrichment_lock(token_address)
    async with token_lock:
        # Re-check after acquiring lock — another coroutine may have fetched already
        if db.is_available():
            now = datetime.now(tz=timezone.utc)
            cached = await db.prisma.tokenenrichmentcache.find_first(
                where={"tokenAddress": token_address, "expiresAt": {"gt": now}},
            )
            if cached:
                return _report_from_cache(token_address, cached, smart_money_flag)

        logger.debug("Enrichment cache miss — fetching from Birdeye for %s", token_address[:8])

        # Endpoints 9–17, excluding 13 (resolved via SmartMoneyCache)
        (
            security_raw,   # 9
            price_raw,      # 10
            holders_raw,    # 11
            _dist_raw,      # 12
            overview_raw,   # 14
            trade_raw,      # 15
            _txs_raw,       # 16
            liquidity_raw,  # 17
        ) = await asyncio.gather(
            _safe(birdeye.get_token_security(token_address)),
            _safe(birdeye.get_price_stats(token_address)),
            _safe(birdeye.get_token_holders(token_address)),
            _safe(birdeye.get_holder_distribution(token_address)),
            _safe(birdeye.get_token_overview(token_address)),
            _safe(birdeye.get_token_trade_data(token_address)),
            _safe(birdeye.get_token_txs(token_address, limit=5)),
            _safe(birdeye.get_exit_liquidity(token_address)),
        )

        # ── Security score ───────────────────────────────────────────────
        sec_data = security_raw.get("data") or {}
        risk_score_raw = sec_data.get("risk_score") or sec_data.get("riskScore")
        security_score: float | None = None
        if risk_score_raw is not None:
            try:
                security_score = max(0.0, 100.0 - float(risk_score_raw))
            except (TypeError, ValueError):
                pass
        is_honeypot = sec_data.get("is_honeypot") or sec_data.get("isHoneypot")

        # ── Price / momentum ─────────────────────────────────────────────
        price_data = price_raw.get("data") or {}
        momentum_24h = price_data.get("price_change_24h") or price_data.get("priceChange24h")

        # ── Holder count ─────────────────────────────────────────────────
        holders_data = holders_raw.get("data") or {}
        holder_count = holders_data.get("holder_count") or holders_data.get("holderCount")

        # ── Buy/sell ratio ───────────────────────────────────────────────
        trade_data = trade_raw.get("data") or {}
        buy_vol = float(trade_data.get("buy_volume_24h") or trade_data.get("buyVolume24h") or 0)
        sell_vol = float(trade_data.get("sell_volume_24h") or trade_data.get("sellVolume24h") or 0)
        total_vol = buy_vol + sell_vol
        buy_sell_ratio = round(buy_vol / total_vol, 4) if total_vol > 0 else None

        # ── Liquidity ────────────────────────────────────────────────────
        liq_data = liquidity_raw.get("data") or {}
        total_liquidity_usd = liq_data.get("total_liquidity_usd") or liq_data.get("totalLiquidityUsd")

        # ── Token overview ───────────────────────────────────────────────
        ov_data = overview_raw.get("data") or {}
        symbol = ov_data.get("symbol")
        price = ov_data.get("price")
        market_cap = ov_data.get("market_cap") or ov_data.get("marketCap") or ov_data.get("mc")
        volume_24h = ov_data.get("volume_24h") or ov_data.get("v24hUSD")

        report = TokenMiniReport(
            token_address=token_address,
            security_score=security_score,
            is_honeypot=bool(is_honeypot) if is_honeypot is not None else None,
            smart_money_flag=smart_money_flag,
            momentum_24h=float(momentum_24h) if momentum_24h is not None else None,
            holder_count=int(holder_count) if holder_count is not None else None,
            buy_sell_ratio=buy_sell_ratio,
            total_liquidity_usd=float(total_liquidity_usd) if total_liquidity_usd is not None else None,
            symbol=symbol,
            price=float(price) if price is not None else None,
            market_cap=float(market_cap) if market_cap is not None else None,
            volume_24h=float(volume_24h) if volume_24h is not None else None,
        )

        # ── Persist to cache ─────────────────────────────────────────────
        if db.is_available():
            expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=6)
            try:
                await db.prisma.tokenenrichmentcache.upsert(
                    where={"tokenAddress": token_address},
                    data={
                        "create": {
                            "tokenAddress": token_address,
                            "expiresAt": expires_at,
                            "securityScore": report.security_score,
                            "isHoneypot": report.is_honeypot,
                            "momentum24h": report.momentum_24h,
                            "holderCount": report.holder_count,
                            "buySellRatio": report.buy_sell_ratio,
                            "liquidityUsd": report.total_liquidity_usd,
                            "symbol": report.symbol,
                            "price": report.price,
                            "marketCap": report.market_cap,
                            "volume24h": report.volume_24h,
                        },
                        "update": {
                            "expiresAt": expires_at,
                            "securityScore": report.security_score,
                            "isHoneypot": report.is_honeypot,
                            "momentum24h": report.momentum_24h,
                            "holderCount": report.holder_count,
                            "buySellRatio": report.buy_sell_ratio,
                            "liquidityUsd": report.total_liquidity_usd,
                            "symbol": report.symbol,
                            "price": report.price,
                            "marketCap": report.market_cap,
                            "volume24h": report.volume_24h,
                        },
                    },
                )
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
            db_wallet = await db.prisma.wallet.find_unique(
                where={"address": wallet_address}
            )
            if db_wallet:
                wallet_id = db_wallet.id
        except Exception as exc:
            logger.debug("Wallet FK lookup failed for %s: %s", wallet_address[:8], exc)

    try:
        await db.prisma.tradeevent.upsert(
            where={"signature": signature},
            data={
                "create": {
                    "signature": signature,
                    "walletId": wallet_id,
                    "walletLabel": wallet_label,
                    "tokenAddress": token_address,
                    "tokenSymbol": token_symbol,
                    "side": side_str,
                    "usdValue": usd_value,
                    "timestamp": ts,
                    "securityScore": report.security_score,
                    "isHoneypot": report.is_honeypot,
                    "smartMoneyFlag": report.smart_money_flag,
                    "momentum24h": report.momentum_24h,
                    "holderCount": report.holder_count,
                    "buySellRatio": report.buy_sell_ratio,
                    "liquidityUsd": report.total_liquidity_usd,
                    "alertSent": False,
                },
                # On conflict (same signature), don't overwrite — trade is already stored
                "update": {},
            },
        )
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
        watchers = await db.prisma.userwatchlist.find_many(
            where={"walletId": wallet_id}
        )
    except Exception as exc:
        logger.debug("Watchlist query failed: %s", exc)
        return

    for watcher in watchers:
        asyncio.create_task(
            send_personal_trade_alert(
                telegram_user_id=int(watcher.telegramUserId),
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
    elif event_type == "LARGE_TRADE_TXS":
        wallet_label = "Whale Alert"

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
                db_wallet = await db.prisma.wallet.find_unique(
                    where={"address": wallet_address}
                )
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


async def _safe(coro) -> dict[str, Any]:
    """Run a coroutine and return its result dict, or {} on any error."""
    try:
        return await coro
    except Exception as exc:
        logger.debug("Enrichment sub-call failed: %s", exc)
        return {}
