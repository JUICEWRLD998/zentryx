"""
REST polling worker for live trade data.

Uses Birdeye's token transaction endpoint (endpoint 16) to monitor recent
large trades. The monitored token list is refreshed every 15 minutes from
Birdeye's trending tokens endpoint (endpoint 20), so the worker automatically
follows the tokens with the most on-chain activity.

Falls back to a hardcoded list of 6 popular tokens if the trending fetch fails.
"""
from __future__ import annotations

import asyncio
import logging
import time

from services import birdeye

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECS = 60          # how often to poll each token (1 minute)
MIN_VALUE_USD = 1_000            # minimum trade size to emit ($1,000)
MAX_SEEN: int = 5_000            # cap on dedup cache
TOKEN_POLL_DELAY = 2.0           # seconds between consecutive token polls (sequential, not parallel)
TRENDING_REFRESH_SECS = 900      # refresh trending token list every 15 minutes
TRENDING_TOKEN_LIMIT = 20        # top N trending tokens to monitor

# Hardcoded fallback — used when the trending fetch fails
_DEFAULT_TOKENS: list[dict] = [
    {"address": "So11111111111111111111111111111111111111112",  "symbol": "SOL"},
    {"address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "symbol": "USDC"},
    {"address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "symbol": "BONK"},
    {"address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "symbol": "WIF"},
    {"address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  "symbol": "JUP"},
    {"address": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "symbol": "PYTH"},
]

# Live token list — populated on startup, refreshed every TRENDING_REFRESH_SECS
MONITORED_TOKENS: list[dict] = list(_DEFAULT_TOKENS)

_seen_tx_ids: set[str] = set()


async def refresh_monitored_tokens() -> None:
    """
    Fetch the top trending tokens by 24h volume from Birdeye and replace
    MONITORED_TOKENS. Falls back silently to the current list on any error.
    """
    global MONITORED_TOKENS
    try:
        raw = await birdeye.get_trending_tokens(
            sort_by="v24hUSD", sort_type="desc", limit=TRENDING_TOKEN_LIMIT
        )
        # Birdeye tokenlist response: {"data": {"tokens": [...]} or {"items": [...]}}
        data = raw.get("data") or {}
        items: list[dict] = data.get("tokens") or data.get("items") or []
        if not items:
            logger.warning("Trending tokens returned empty list — keeping current token list.")
            return

        fresh = [
            {
                "address": item.get("address") or item.get("mint") or "",
                "symbol": item.get("symbol") or item.get("name") or "UNKNOWN",
            }
            for item in items
            if item.get("address") or item.get("mint")
        ]

        if fresh:
            MONITORED_TOKENS = fresh
            symbols = ", ".join(t["symbol"] for t in MONITORED_TOKENS[:6])
            if len(MONITORED_TOKENS) > 6:
                symbols += f"... +{len(MONITORED_TOKENS) - 6} more"
            logger.info("Trending token list refreshed — monitoring %d tokens: %s", len(MONITORED_TOKENS), symbols)
    except Exception as exc:
        logger.warning("Failed to refresh trending tokens — keeping current list: %s", exc)


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
    cutoff = now - 600  # only process txs from the last 10 minutes

    total = len(txs)
    skipped_dup = skipped_stale = skipped_usd = skipped_untracked = emitted = 0

    # Log raw keys of first tx once per token to diagnose field name mismatches
    if txs:
        logger.info("[%s] first tx keys: %s", symbol, list(txs[0].keys()))

    for tx in txs:
        # Deduplicate — try every known Birdeye field name variant for the tx hash
        tx_hash = (
            tx.get("txHash")
            or tx.get("tx_hash")
            or tx.get("hash")
            or tx.get("signature")
            or tx.get("id")
            or tx.get("transactionHash")
            or ""
        )
        if not tx_hash:
            # Unknown hash field — log once at warning level so we can adapt
            logger.warning(
                "[%s] tx has no recognised hash field; available keys: %s",
                symbol, list(tx.keys()),
            )
            skipped_dup += 1
            continue
        if tx_hash in _seen_tx_ids:
            skipped_dup += 1
            continue

        # Skip old transactions
        ts = tx.get("block_unix_time") or tx.get("blockUnixTime") or tx.get("timestamp") or 0
        if ts < cutoff:
            skipped_stale += 1
            continue

        # Filter by minimum USD value
        value_usd = float(tx.get("volume_usd") or tx.get("volumeUSD") or tx.get("volume") or tx.get("value") or tx.get("amount") or 0)
        if value_usd < MIN_VALUE_USD:
            skipped_usd += 1
            continue

        # Only emit trades from tracked wallets
        owner = tx.get("owner") or tx.get("wallet") or ""
        if not owner or owner not in tracked_wallet_addrs:
            skipped_untracked += 1
            continue

        _seen_tx_ids.add(tx_hash)
        _prune_seen()

        from services.wallet_discovery import tracked_wallets
        tw = tracked_wallets.get(owner)
        wallet_label: str = tw.label if tw else f"{owner[:8]}…"

        side = (tx.get("side") or tx.get("type") or "unknown").upper()

        synthetic_event: dict = {
            "type": "WALLET_TXS",
            "data": {
                "txHash": tx_hash,
                "owner": owner,
                "wallet_label": wallet_label,
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
        "[%s] polled %d txs → emitted=%d dup=%d stale=%d below_usd=%d untracked=%d",
        symbol, total, emitted, skipped_dup, skipped_stale, skipped_usd, skipped_untracked,
    )


async def run_polling_worker(on_event) -> None:
    """
    Continuously polls Solana token transactions for large whale trades.
    Runs forever — called from main.py lifespan as a background task.

    On startup, fetches the current trending token list from Birdeye.
    Refreshes that list every TRENDING_REFRESH_SECS (15 minutes).
    """
    from services.wallet_discovery import tracked_wallets

    # Fetch trending tokens before first poll round
    await refresh_monitored_tokens()

    logger.info(
        "REST polling worker started — monitoring %d tokens (interval=%ds, min_usd=$%s).",
        len(MONITORED_TOKENS), POLL_INTERVAL_SECS, f"{MIN_VALUE_USD:,}",
    )

    last_trending_refresh = time.time()

    while True:
        # Refresh trending token list periodically
        if time.time() - last_trending_refresh >= TRENDING_REFRESH_SECS:
            await refresh_monitored_tokens()
            last_trending_refresh = time.time()

        # Snapshot current tracked wallet addresses for cross-reference
        tracked_addrs = set(tracked_wallets.keys())

        # Poll tokens sequentially with a delay to respect rate limits
        for token in MONITORED_TOKENS:
            await _poll_token(token, tracked_addrs, on_event)
            await asyncio.sleep(TOKEN_POLL_DELAY)

        logger.debug("Token polling round complete — %d tokens checked.", len(MONITORED_TOKENS))

        await asyncio.sleep(POLL_INTERVAL_SECS)
