"""
REST polling fallback for live trade data.

Uses Birdeye's public token transaction endpoint (endpoint 16) to monitor
recent large trades on popular Solana tokens. When a tracked whale wallet
appears as the owner, the trade is labelled accordingly; otherwise it is
emitted as an anonymous "large trade" event — matching the LARGE_TRADE_TXS
WebSocket channel semantics.

This path works on the Birdeye free tier and requires no paid-tier wallet
endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import time

from services import birdeye

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECS = 1200        # how often to poll each token (20 minutes, down from 5)
MIN_VALUE_USD = 2_000            # minimum trade size to emit
MAX_SEEN: int = 5_000            # cap on dedup cache
TOKEN_POLL_DELAY = 5.0           # seconds between consecutive token polls (sequential, not parallel)

# Popular Solana tokens to monitor (mint addresses)
MONITORED_TOKENS: list[dict] = [
    {"address": "So11111111111111111111111111111111111111112",  "symbol": "SOL"},
    {"address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "symbol": "USDC"},
    {"address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK"},
    {"address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "symbol": "WIF"},
    {"address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  "symbol": "JUP"},
    {"address": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "symbol": "PYTH"},
]

_seen_tx_ids: set[str] = set()


def _prune_seen() -> None:
    global _seen_tx_ids
    if len(_seen_tx_ids) > MAX_SEEN:
        items = list(_seen_tx_ids)
        _seen_tx_ids = set(items[MAX_SEEN // 2 :])


async def _poll_token(token: dict, tracked_wallet_addrs: set[str], on_event) -> None:
    """Fetch recent transactions for one token and emit large trades."""
    token_address = token["address"]
    symbol = token["symbol"]
    try:
        data = await birdeye.get_token_txs(token_address, limit=20)
    except Exception as exc:
        logger.debug("Token tx poll %s failed: %s", symbol, exc)
        return

    # Birdeye token txs response structure: data.items or data.list
    data_block = data.get("data") or {}
    txs: list[dict] = data_block.get("items") or data_block.get("list") or []

    now = int(time.time())
    cutoff = now - POLL_INTERVAL_SECS * 3  # only process recent txs

    total = len(txs)
    skipped_dup = skipped_stale = skipped_usd = emitted = 0

    for tx in txs:
        # Deduplicate
        tx_hash = tx.get("txHash") or tx.get("hash") or tx.get("signature") or ""
        if not tx_hash or tx_hash in _seen_tx_ids:
            skipped_dup += 1
            continue

        # Skip old transactions
        ts = tx.get("blockUnixTime") or tx.get("timestamp") or 0
        if ts < cutoff:
            skipped_stale += 1
            continue

        # Filter by minimum USD value
        value_usd = float(tx.get("volumeUSD") or tx.get("value") or tx.get("amount") or 0)
        if value_usd < MIN_VALUE_USD:
            skipped_usd += 1
            continue

        _seen_tx_ids.add(tx_hash)
        _prune_seen()

        owner = tx.get("owner") or tx.get("wallet") or ""
        wallet_label = None
        if owner and owner in tracked_wallet_addrs:
            from services.wallet_discovery import tracked_wallets
            tw = tracked_wallets.get(owner)
            wallet_label = tw.label if tw else f"{owner[:6]}…"

        side = (tx.get("side") or tx.get("type") or "unknown").upper()

        synthetic_event: dict = {
            "type": "LARGE_TRADE_TXS" if not wallet_label else "WALLET_TXS",
            "data": {
                "txHash": tx_hash,
                "owner": owner,
                "wallet_label": wallet_label or "Unknown",
                "tokenAddress": token_address,
                "tokenSymbol": symbol,
                "side": side,
                "volumeUSD": value_usd,
                "blockUnixTime": ts,
            },
        }
        emitted += 1
        try:
            asyncio.create_task(on_event(synthetic_event))
        except Exception as exc:
            logger.debug("Enrichment task error: %s", exc)

    logger.info(
        "[%s] polled %d txs → emitted=%d dup=%d stale=%d below_usd=%d (min=$%s)",
        symbol, total, emitted, skipped_dup, skipped_stale, skipped_usd, MIN_VALUE_USD,
    )


async def run_polling_worker(on_event) -> None:
    """
    Continuously polls popular Solana token transactions for large trades.
    Runs forever — called from main.py lifespan as a background task.
    """
    from services.wallet_discovery import tracked_wallets

    logger.info(
        "REST polling worker started — monitoring %d tokens (interval=%ds, min_usd=$%s).",
        len(MONITORED_TOKENS), POLL_INTERVAL_SECS, f"{MIN_VALUE_USD:,}",
    )

    while True:
        # Snapshot current tracked wallet addresses for cross-reference
        tracked_addrs = set(tracked_wallets.keys())

        # Poll tokens sequentially with a delay to respect rate limits
        for token in MONITORED_TOKENS:
            await _poll_token(token, tracked_addrs, on_event)
            await asyncio.sleep(TOKEN_POLL_DELAY)

        logger.debug("Token polling round complete — %d tokens checked.", len(MONITORED_TOKENS))

        await asyncio.sleep(POLL_INTERVAL_SECS)
