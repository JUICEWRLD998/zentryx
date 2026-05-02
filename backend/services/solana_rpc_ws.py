"""
Solana RPC WebSocket client — real-time whale trade detection.

Replaces the Birdeye WebSocket (premium-only) with Solana's native
`accountSubscribe` RPC method. Subscribes to each of the top 15 tracked
whale wallets and detects token balance changes that signal a DEX swap.

How it works:
  1. For every tracked wallet, send an `accountSubscribe` request to the
     Solana RPC WebSocket endpoint.
  2. On each `accountNotification`, fetch the latest confirmed transaction
     signatures for that wallet (one `getSignaturesForAddress` call).
  3. Fetch the full transaction detail (`getTransaction`) for the newest
     unseen signature to extract token deltas and USD value.
  4. Normalise the result into the same event schema used by the rest of the
     pipeline and pass it to `on_event(payload)`.

Event schema emitted (identical to the Birdeye WS / polling worker):
  {
    "type": "WALLET_TXS",
    "data": {
        "txHash": "<signature>",
        "owner": "<wallet_address>",
        "wallet_label": "<label>",
        "tokenAddress": "<mint>",
        "tokenSymbol": "<symbol or None>",
        "side": "BUY" | "SELL" | "UNKNOWN",
        "volumeUSD": <float>,
        "blockUnixTime": <int>,
    }
  }

Latency: 2–5 s (Triton One free tier).
Cost: $0 — fully free RPC endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Default to public Triton One mainnet endpoint (free tier, no key required)
_DEFAULT_WS_URL = "wss://api.mainnet-beta.solana.com"
_DEFAULT_HTTP_URL = "https://api.mainnet-beta.solana.com"

RECONNECT_DELAY_SECS = 5
MAX_RECONNECT_DELAY_SECS = 300        # 5-minute cap
_MIN_USD_VALUE = 1000.0                # pre-filter: skip tiny moves before enrichment
_SEEN_SIGNATURES_MAX = 10_000        # dedup cache cap
_SIGNATURE_FETCH_LIMIT = 5           # how many recent sigs to check per notification
_SOL_PRICE_REFRESH_SECS = 60         # refresh SOL/USD price cache every minute

# ── Module-level state ─────────────────────────────────────────────────────────

# Dedup cache: tracks signatures already emitted to prevent double-processing
_seen_signatures: set[str] = set()

# Subscription ID → wallet address mapping (set during subscribe phase)
_sub_id_to_wallet: dict[int, str] = {}

# Running estimate of SOL/USD price (refreshed every minute via RPC call)
_sol_price_usd: float = 150.0
_sol_price_fetched_at: float = 0.0


# ── Helpers ────────────────────────────────────────────────────────────────────


def _prune_seen() -> None:
    """Keep the dedup set from growing unbounded."""
    global _seen_signatures
    if len(_seen_signatures) > _SEEN_SIGNATURES_MAX:
        items = list(_seen_signatures)
        _seen_signatures = set(items[_SEEN_SIGNATURES_MAX // 2 :])


def _ws_url() -> str:
    return os.getenv("SOLANA_RPC_WS_URL", _DEFAULT_WS_URL)


def _http_url() -> str:
    return os.getenv("SOLANA_RPC_HTTP_URL", _DEFAULT_HTTP_URL)


async def _rpc_post(method: str, params: list[Any]) -> dict[str, Any]:
    """
    Fire a single JSON-RPC POST to the Solana HTTP endpoint.
    Returns the parsed response dict, or {} on error.
    """
    import httpx  # httpx is already a dependency (used by birdeye.py)

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_http_url(), json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.debug("RPC HTTP %s failed: %s", method, exc)
        return {}


async def _refresh_sol_price() -> None:
    """
    Update the module-level SOL/USD estimate once per minute.
    Uses a cheap `getMultipleAccounts` trick on the SOL/USDC Pyth oracle
    — falls back to the last known value on any error.
    """
    global _sol_price_usd, _sol_price_fetched_at

    now = time.monotonic()
    if now - _sol_price_fetched_at < _SOL_PRICE_REFRESH_SECS:
        return  # still fresh

    # Use getRecentBlockhash result to derive SOL lamport cost as a proxy;
    # simpler: query Binance public REST (no key, always accessible)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "SOLUSDT"},
            )
            r.raise_for_status()
            _sol_price_usd = float(r.json()["price"])
            _sol_price_fetched_at = now
            logger.debug("SOL/USD price refreshed: $%.2f", _sol_price_usd)
    except Exception as exc:
        logger.debug("SOL price refresh failed (using last known $%.2f): %s", _sol_price_usd, exc)


def _lamports_to_usd(lamports: int) -> float:
    """Convert lamport delta to USD using the current SOL price."""
    sol = lamports / 1_000_000_000  # 1 SOL = 1e9 lamports
    return round(sol * _sol_price_usd, 4)


async def _fetch_latest_signature(wallet_address: str) -> str | None:
    """
    Return the most recent confirmed transaction signature for a wallet,
    or None on failure.
    """
    resp = await _rpc_post(
        "getSignaturesForAddress",
        [wallet_address, {"limit": _SIGNATURE_FETCH_LIMIT, "commitment": "confirmed"}],
    )
    sigs = resp.get("result") or []
    if not sigs:
        return None
    return sigs[0].get("signature")


async def _fetch_transaction(signature: str) -> dict[str, Any] | None:
    """
    Fetch the full transaction detail for a given signature.
    Returns the `result` block or None.
    """
    resp = await _rpc_post(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0,
            },
        ],
    )
    return resp.get("result")


def _parse_token_changes(
    tx: dict[str, Any], wallet_address: str
) -> tuple[str | None, str | None, str, float]:
    """
    Extract (token_address, symbol, side, usd_value) from a parsed transaction.

    Strategy:
      1. Scan `meta.postTokenBalances` vs `meta.preTokenBalances` for this
         wallet's token account changes — the largest delta wins.
      2. Fall back to SOL native balance delta if no SPL token change found.

    Returns:
      token_address: SPL mint or 'So11111111111111111111111111111111111111112' for SOL
      symbol:        token symbol string if available, else None
      side:          'BUY' | 'SELL' | 'UNKNOWN'
      usd_value:     absolute USD value of the move (0.0 if unresolvable)
    """
    SOL_MINT = "So11111111111111111111111111111111111111112"
    meta = tx.get("meta") or {}
    inner_ixs = meta.get("innerInstructions") or []

    # ── SPL Token balance deltas ───────────────────────────────────────────
    pre_balances: dict[str, float] = {}
    post_balances: dict[str, float] = {}
    mint_by_index: dict[str, str] = {}
    symbol_by_mint: dict[str, str] = {}

    for entry in meta.get("preTokenBalances") or []:
        owner = entry.get("owner")
        if owner != wallet_address:
            continue
        mint = entry.get("mint", "")
        amt = float((entry.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        pre_balances[mint] = amt
        mint_by_index[str(entry.get("accountIndex", ""))] = mint
        info = (entry.get("uiTokenAmount") or {})
        # symbol not always present in preTokenBalances — populated below from post
        _ = info

    for entry in meta.get("postTokenBalances") or []:
        owner = entry.get("owner")
        if owner != wallet_address:
            continue
        mint = entry.get("mint", "")
        amt = float((entry.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        post_balances[mint] = amt
        # Try to pick up the symbol from parsed instruction info
        symbol = (
            (entry.get("uiTokenAmount") or {}).get("symbol")
            or None
        )
        if symbol:
            symbol_by_mint[mint] = symbol

    # Find largest absolute change
    best_mint: str | None = None
    best_delta: float = 0.0

    all_mints = set(pre_balances) | set(post_balances)
    for mint in all_mints:
        delta = post_balances.get(mint, 0.0) - pre_balances.get(mint, 0.0)
        if abs(delta) > abs(best_delta):
            best_delta = delta
            best_mint = mint

    if best_mint and best_delta != 0.0:
        side = "BUY" if best_delta > 0 else "SELL"
        # USD value: for SPL tokens we don't have a live price — use SOL-denominated
        # fee approximation as floor; enrichment pipeline will refine it.
        # We compute a rough USD value from the SOL cost of the swap instead.
        sol_deltas = meta.get("preBalances") or []
        sol_post = meta.get("postBalances") or []
        account_keys = (tx.get("transaction") or {}).get("message", {}).get("accountKeys") or []

        signer_sol_delta = 0
        for i, key_info in enumerate(account_keys):
            key = key_info.get("pubkey") if isinstance(key_info, dict) else key_info
            if key == wallet_address and i < len(sol_deltas) and i < len(sol_post):
                signer_sol_delta = abs(sol_post[i] - sol_deltas[i])
                break

        usd_value = _lamports_to_usd(signer_sol_delta) if signer_sol_delta > 0 else 0.0
        symbol = symbol_by_mint.get(best_mint)
        return best_mint, symbol, side, usd_value

    # ── SOL native fallback ────────────────────────────────────────────────
    pre_sol = meta.get("preBalances") or []
    post_sol = meta.get("postBalances") or []
    account_keys = (tx.get("transaction") or {}).get("message", {}).get("accountKeys") or []

    for i, key_info in enumerate(account_keys):
        key = key_info.get("pubkey") if isinstance(key_info, dict) else key_info
        if key == wallet_address and i < len(pre_sol) and i < len(post_sol):
            delta_lamports = post_sol[i] - pre_sol[i]
            if abs(delta_lamports) > 10_000:  # skip dust / fees
                side = "BUY" if delta_lamports < 0 else "SELL"  # spending SOL = buying token
                usd_value = _lamports_to_usd(abs(delta_lamports))
                return SOL_MINT, "SOL", side, usd_value
            break

    return None, None, "UNKNOWN", 0.0


async def _process_wallet_notification(wallet_address: str, on_event) -> None:
    """
    Called when `accountNotification` fires for a wallet.
    Fetches the latest transaction, parses it, and emits an event if it
    passes the USD threshold and has not been seen before.
    """
    from services.wallet_discovery import tracked_wallets  # live state

    # Refresh SOL price if stale
    await _refresh_sol_price()

    signature = await _fetch_latest_signature(wallet_address)
    if not signature or signature in _seen_signatures:
        return

    tx = await _fetch_transaction(signature)
    if not tx:
        return

    # Skip transactions that errored on-chain
    if (tx.get("meta") or {}).get("err") is not None:
        _seen_signatures.add(signature)
        _prune_seen()
        return

    token_address, symbol, side, usd_value = _parse_token_changes(tx, wallet_address)

    if not token_address:
        _seen_signatures.add(signature)
        _prune_seen()
        return

    if usd_value < _MIN_USD_VALUE:
        _seen_signatures.add(signature)
        _prune_seen()
        logger.debug(
            "Skipping small trade $%.2f from %s…", usd_value, wallet_address[:8]
        )
        return

    _seen_signatures.add(signature)
    _prune_seen()

    tw = tracked_wallets.get(wallet_address)
    wallet_label = tw.label if tw else f"{wallet_address[:6]}…"
    block_time = tx.get("blockTime") or int(time.time())

    event: dict[str, Any] = {
        "type": "WALLET_TXS",
        "data": {
            "txHash": signature,
            "owner": wallet_address,
            "wallet_label": wallet_label,
            "tokenAddress": token_address,
            "tokenSymbol": symbol,
            "side": side,
            "volumeUSD": usd_value,
            "blockUnixTime": block_time,
        },
    }

    logger.info(
        "Solana RPC | %s | %s | $%.2f | %s…",
        wallet_label,
        side,
        usd_value,
        token_address[:8],
    )

    try:
        asyncio.create_task(on_event(event))
    except Exception as exc:
        logger.warning("on_event task error: %s", exc)


# ── WebSocket connection ───────────────────────────────────────────────────────


async def _run_connection(on_event) -> None:
    """
    Single WebSocket connection attempt.
    Opens the Solana RPC WS, subscribes to all tracked wallet accounts,
    then routes incoming notifications to the processing pipeline.
    """
    from services.wallet_discovery import tracked_wallets  # live state

    _sub_id_to_wallet.clear()
    wallet_addresses = list(tracked_wallets.keys())

    if not wallet_addresses:
        logger.warning("No tracked wallets found — Solana RPC WS will wait for discovery.")
        await asyncio.sleep(30)
        return

    url = _ws_url()
    logger.info(
        "Connecting to Solana RPC WebSocket (%s) for %d wallet(s)…",
        url,
        len(wallet_addresses),
    )

    async with websockets.connect(
        url,
        ping_interval=30,
        ping_timeout=15,
        max_size=10 * 1024 * 1024,  # 10 MB — handles large account data blobs
    ) as ws:
        # Subscribe to each wallet with accountSubscribe
        for idx, address in enumerate(wallet_addresses):
            subscribe_msg = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": idx + 1,  # unique request ID per subscription
                    "method": "accountSubscribe",
                    "params": [
                        address,
                        {"encoding": "base64", "commitment": "confirmed"},
                    ],
                }
            )
            await ws.send(subscribe_msg)

        logger.info(
            "Solana RPC WS connected. Sent %d accountSubscribe request(s). "
            "Awaiting subscription confirmations…",
            len(wallet_addresses),
        )

        pending_ids = {i + 1: wallet_addresses[i] for i in range(len(wallet_addresses))}

        async for raw in ws:
            try:
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Non-JSON WS message (ignored): %s", str(raw)[:100])
                continue

            # ── Subscription confirmation ─────────────────────────────────
            # Response to accountSubscribe: {"id": N, "result": <sub_id>}
            msg_id = msg.get("id")
            if msg_id is not None and "result" in msg:
                result = msg["result"]
                if isinstance(result, int) and msg_id in pending_ids:
                    wallet_addr = pending_ids.pop(msg_id)
                    _sub_id_to_wallet[result] = wallet_addr
                    logger.info(
                        "  ✓ accountSubscribe confirmed | sub_id=%d | wallet=%s…",
                        result,
                        wallet_addr[:8],
                    )
                    if not pending_ids:
                        logger.info(
                            "All %d wallet subscriptions active. "
                            "Monitoring for whale trades…",
                            len(_sub_id_to_wallet),
                        )
                continue

            # ── Account notification ──────────────────────────────────────
            # {"jsonrpc":"2.0","method":"accountNotification","params":{...}}
            if msg.get("method") == "accountNotification":
                params = msg.get("params") or {}
                sub_id = params.get("subscription")
                wallet_addr = _sub_id_to_wallet.get(sub_id)
                if wallet_addr:
                    asyncio.create_task(
                        _process_wallet_notification(wallet_addr, on_event)
                    )
                continue

            logger.debug("Unhandled WS message type: %s", str(msg)[:200])


async def run_solana_rpc_ws(on_event) -> None:
    """
    Main loop that keeps the Solana RPC WebSocket connection alive with
    exponential-backoff auto-reconnect.

    Signature matches `run_birdeye_ws` — a drop-in replacement in main.py.
    """
    delay = RECONNECT_DELAY_SECS
    attempt = 0

    while True:
        attempt += 1
        try:
            await _run_connection(on_event)
            # Clean exit (e.g. server closed gracefully) — reset delay
            delay = RECONNECT_DELAY_SECS
            logger.info("Solana RPC WS connection closed cleanly. Reconnecting…")

        except ConnectionClosed as exc:
            logger.warning(
                "Solana RPC WS closed (attempt %d): %s. Reconnecting in %ds…",
                attempt, exc, delay,
            )
        except OSError as exc:
            logger.warning(
                "Solana RPC WS network error (attempt %d): %s. Reconnecting in %ds…",
                attempt, exc, delay,
            )
        except Exception as exc:
            logger.warning(
                "Solana RPC WS unexpected error (attempt %d): %s. Reconnecting in %ds…",
                attempt, exc, delay,
            )
            delay = min(delay * 2, MAX_RECONNECT_DELAY_SECS)

        await asyncio.sleep(delay)
