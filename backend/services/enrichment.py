"""
Alert enrichment pipeline — Phase 4.

On each incoming WebSocket trade event we concurrently hit endpoints 9–17
to build a TokenMiniReport, then broadcast the enriched event to all
connected frontend clients and fire a Telegram alert.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from models.schemas import TokenMiniReport
from services import birdeye
from services.ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)


async def _safe(coro) -> dict[str, Any]:
    """Run a coroutine and return its result dict, or {} on any error."""
    try:
        return await coro
    except Exception as exc:
        logger.debug("Enrichment sub-call failed: %s", exc)
        return {}


async def build_mini_report(token_address: str) -> TokenMiniReport:
    """
    Concurrently fetch all 9 token-intelligence endpoints and compose a
    TokenMiniReport. Failures on individual endpoints are swallowed so
    that one bad endpoint never kills the whole report.

    Endpoints used: 8–17 (9 calls, all fired in parallel via asyncio.gather)
    """
    (
        security_raw,   # 9
        price_raw,      # 10
        holders_raw,    # 11
        _dist_raw,      # 12
        smart_raw,      # 13
        overview_raw,   # 14
        trade_raw,      # 15
        _txs_raw,       # 16
        liquidity_raw,  # 17
    ) = await asyncio.gather(
        _safe(birdeye.get_token_security(token_address)),
        _safe(birdeye.get_price_stats(token_address)),
        _safe(birdeye.get_token_holders(token_address)),
        _safe(birdeye.get_holder_distribution(token_address)),
        _safe(birdeye.get_smart_money_tokens()),
        _safe(birdeye.get_token_overview(token_address)),
        _safe(birdeye.get_token_trade_data(token_address)),
        _safe(birdeye.get_token_txs(token_address, limit=5)),
        _safe(birdeye.get_exit_liquidity(token_address)),
    )

    # ── Security score ────────────────────────────────────────────────────
    sec_data = security_raw.get("data") or {}
    risk_score_raw = sec_data.get("risk_score") or sec_data.get("riskScore")
    # Birdeye may return a risk score 0–100 (higher = riskier).
    # We invert it to a safety score.
    security_score: float | None = None
    if risk_score_raw is not None:
        try:
            security_score = max(0.0, 100.0 - float(risk_score_raw))
        except (TypeError, ValueError):
            pass

    is_honeypot = sec_data.get("is_honeypot") or sec_data.get("isHoneypot")

    # ── Smart money flag ──────────────────────────────────────────────────
    sm_items = (smart_raw.get("data") or {}).get("items") or []
    smart_money_addresses = {item.get("address") for item in sm_items if item.get("address")}
    smart_money_flag = token_address in smart_money_addresses

    # ── Price / momentum ──────────────────────────────────────────────────
    price_data = price_raw.get("data") or {}
    momentum_24h = price_data.get("price_change_24h") or price_data.get("priceChange24h")

    # ── Holder count ──────────────────────────────────────────────────────
    holders_data = holders_raw.get("data") or {}
    holder_count = holders_data.get("holder_count") or holders_data.get("holderCount")

    # ── Buy/sell ratio ────────────────────────────────────────────────────
    trade_data = trade_raw.get("data") or {}
    buy_vol = float(trade_data.get("buy_volume_24h") or trade_data.get("buyVolume24h") or 0)
    sell_vol = float(trade_data.get("sell_volume_24h") or trade_data.get("sellVolume24h") or 0)
    total_vol = buy_vol + sell_vol
    buy_sell_ratio = round(buy_vol / total_vol, 4) if total_vol > 0 else None

    # ── Liquidity ─────────────────────────────────────────────────────────
    liq_data = liquidity_raw.get("data") or {}
    total_liquidity_usd = liq_data.get("total_liquidity_usd") or liq_data.get("totalLiquidityUsd")

    # ── Token overview ────────────────────────────────────────────────────
    ov_data = overview_raw.get("data") or {}
    symbol = ov_data.get("symbol")
    price = ov_data.get("price")
    market_cap = ov_data.get("market_cap") or ov_data.get("marketCap") or ov_data.get("mc")
    volume_24h = ov_data.get("volume_24h") or ov_data.get("v24hUSD")

    return TokenMiniReport(
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


async def process_trade_event(raw_event: dict[str, Any]) -> None:
    """
    Called for every incoming Birdeye WS event.
    1. Validate it's a trade we care about.
    2. Concurrently enrich with token mini-report.
    3. Broadcast enriched event to all WS frontend clients.
    4. Send Telegram alert (non-blocking, fire-and-forget).
    """
    from services.telegram import send_trade_alert  # late import to avoid circular
    from services.wallet_discovery import tracked_wallets

    event_type = raw_event.get("type", "")
    data = raw_event.get("data") or {}

    # Only process transaction events
    if event_type not in ("WALLET_TXS", "LARGE_TRADE_TXS"):
        return

    token_address = data.get("token_address") or data.get("tokenAddress") or data.get("mint")
    wallet_address = data.get("wallet") or data.get("owner")
    usd_value = data.get("value_usd") or data.get("valueUsd") or data.get("volume")
    side = data.get("side") or ("buy" if data.get("type") == "BUY" else "sell")
    tx_hash = data.get("tx_hash") or data.get("txHash") or data.get("signature")
    block_time = data.get("block_time") or data.get("blockTime")

    if not token_address:
        return

    # Determine wallet label if this is a tracked wallet event
    wallet_label = None
    if wallet_address and wallet_address in tracked_wallets:
        wallet_label = tracked_wallets[wallet_address].label
    elif event_type == "LARGE_TRADE_TXS":
        wallet_label = "Whale Alert"

    if wallet_label is None:
        return  # Not a tracked wallet or large trade — ignore

    logger.info("Processing trade: %s | %s | $%s | %s", wallet_label, side.upper(), usd_value, token_address[:8])

    # Build enriched token report (endpoints 9–17 in parallel)
    try:
        mini_report = await build_mini_report(token_address)
    except Exception as exc:
        logger.warning("Enrichment failed for %s: %s", token_address, exc)
        mini_report = TokenMiniReport(token_address=token_address)

    # Compose broadcast payload
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

    # Broadcast to all frontend WS clients
    await ws_manager.broadcast(broadcast_payload)

    # Telegram alert — fire and forget so it never blocks the pipeline
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
