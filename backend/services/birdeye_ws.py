"""
Birdeye WebSocket client — PRIMARY whale trade detection (premium plan).

Protocol: wss://public-api.birdeye.so/socket?x-api-key=KEY

Subscribes to:
  SUBSCRIBE_WALLET_TXS  — one subscription per tracked whale wallet
  SUBSCRIBE_LARGE_TRADE_TXS — whale alerts for any large trade ($10K+)

Event types Birdeye streams back:
  "WALLET_TXS"       — a tracked wallet made a trade
  "LARGE_TRADE_TXS"  — large trade detected across all of Solana

The normalizer injects `wallet_label` before forwarding to `process_trade_event`
so the enrichment pipeline gets a fully resolved event.

Resubscription:
  Call `request_resubscribe()` any time the tracked wallet set changes.
  The loop will reconnect and resubscribe all current wallets.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

BIRDEYE_WS_BASE = "wss://public-api.birdeye.so/socket"
RECONNECT_DELAY_SECS = 5
MAX_RECONNECT_DELAY_SECS = 120  # 2 minutes cap — premium plan, shorter backoff
LARGE_TRADE_MIN_VOLUME = 10_000  # USD

# Resubscribe event — set() to force a fresh connection with the latest wallet set
_resubscribe_event: asyncio.Event | None = None

# Types we forward to the enrichment pipeline
_TRADE_EVENT_TYPES = {"WALLET_TXS", "LARGE_TRADE_TXS"}

# Types we silently ignore (subscription acks, pings, etc.)
_IGNORED_TYPES = {
    "SUBSCRIBE_WALLET_TXS", "SUBSCRIBE_LARGE_TRADE_TXS",
    "UNSUBSCRIBE_WALLET_TXS", "UNSUBSCRIBE_LARGE_TRADE_TXS",
    "PING", "PONG", "ERROR", "INFO",
}


def _get_resubscribe_event() -> asyncio.Event:
    """Lazy-init the resubscribe event so it's created on the right event loop."""
    global _resubscribe_event
    if _resubscribe_event is None:
        _resubscribe_event = asyncio.Event()
    return _resubscribe_event


def request_resubscribe() -> None:
    """
    Signal the Birdeye WS loop to reconnect and resubscribe all current wallets.
    Safe to call from any coroutine (wallet_discovery does this after each run).
    """
    try:
        _get_resubscribe_event().set()
    except RuntimeError:
        # No running event loop yet — harmless, first connection will subscribe all wallets
        pass


def _build_subscribe_wallet(address: str) -> str:
    return json.dumps({"type": "SUBSCRIBE_WALLET_TXS", "data": {"wallet": address}})


def _build_subscribe_large_trades() -> str:
    return json.dumps(
        {"type": "SUBSCRIBE_LARGE_TRADE_TXS", "data": {"min_volume": LARGE_TRADE_MIN_VOLUME}}
    )


def _normalize_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Normalize a raw Birdeye WS message into the format expected by process_trade_event.

    Injects wallet_label from the in-memory tracked_wallets dict.
    Returns None for non-trade messages (subscription acks, pings, etc.).
    """
    from services.wallet_discovery import tracked_wallets  # live state

    event_type = payload.get("type", "")

    if event_type in _IGNORED_TYPES:
        logger.debug("Birdeye WS ack/ping: %s", event_type)
        return None

    if event_type not in _TRADE_EVENT_TYPES:
        logger.debug("Birdeye WS unknown type (ignoring): %s", event_type)
        return None

    data = payload.get("data") or {}

    # Resolve wallet label — look up from tracked_wallets first, then fall back
    owner = data.get("owner") or data.get("wallet") or ""
    tw = tracked_wallets.get(owner)

    if event_type == "WALLET_TXS":
        if not tw:
            # We subscribed to this wallet but discovery has since rotated it out.
            # Still forward it — enrichment will label it generically.
            wallet_label = f"{owner[:6]}…" if owner else "Unknown Whale"
        else:
            wallet_label = tw.label
    else:
        # LARGE_TRADE_TXS — could be any wallet on Solana
        wallet_label = tw.label if tw else "Whale Alert"

    # Inject the resolved label so enrichment doesn't need to look it up
    enriched_data = dict(data)
    enriched_data["wallet_label"] = wallet_label

    return {"type": event_type, "data": enriched_data}


async def _run_connection(on_event) -> None:
    """
    Single Birdeye WS connection attempt.
    Subscribes to all tracked wallets + large trade stream, then listens.
    Raises ResubscribeRequested when the resubscribe event is set mid-connection.
    """
    from services.wallet_discovery import tracked_wallets  # live state

    resubscribe_event = _get_resubscribe_event()
    resubscribe_event.clear()

    api_key = os.getenv("BIRDEYE_API_KEY", "")
    if not api_key:
        logger.error("BIRDEYE_API_KEY not set — Birdeye WS cannot connect.")
        await asyncio.sleep(60)
        return

    ws_url = f"{BIRDEYE_WS_BASE}?x-api-key={api_key}"
    extra_headers = {
        "x-api-key": api_key,
        "x-chain": "solana",
    }

    wallet_addresses = list(tracked_wallets.keys())
    if not wallet_addresses:
        logger.warning("No tracked wallets found — waiting 30s before Birdeye WS connect.")
        await asyncio.sleep(30)
        return

    logger.info(
        "Connecting to Birdeye WebSocket (premium) for %d wallet(s)...",
        len(wallet_addresses),
    )

    async with websockets.connect(
        ws_url,
        additional_headers=extra_headers,
        ping_interval=20,
        ping_timeout=10,
    ) as ws:
        logger.info("Birdeye WS connected.")

        # Subscribe to each tracked wallet
        for address in wallet_addresses:
            await ws.send(_build_subscribe_wallet(address))
            logger.debug("Subscribed to wallet txs: %s…", address[:8])

        logger.info(
            "Birdeye WS: subscribed %d wallets + large trade stream (min $%s).",
            len(wallet_addresses),
            f"{LARGE_TRADE_MIN_VOLUME:,}",
        )

        # Subscribe to large trade alerts (whale activity across all of Solana)
        await ws.send(_build_subscribe_large_trades())

        # Listen loop — also watch for resubscribe requests
        async def _listen():
            async for raw in ws:
                try:
                    payload: dict[str, Any] = json.loads(raw)
                    event = _normalize_event(payload)
                    if event is not None:
                        await on_event(event)
                except json.JSONDecodeError:
                    logger.warning("Birdeye WS non-JSON message: %s", str(raw)[:200])
                except Exception as exc:
                    logger.exception("Error processing Birdeye WS event: %s", exc)

        async def _watch_resubscribe():
            await resubscribe_event.wait()
            logger.info("Resubscribe requested — closing Birdeye WS connection.")
            await ws.close()

        # Run both concurrently; whichever finishes first wins
        listen_task = asyncio.create_task(_listen())
        resub_task = asyncio.create_task(_watch_resubscribe())
        try:
            done, pending = await asyncio.wait(
                {listen_task, resub_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            # Re-raise any exception from the listen task
            for t in done:
                if not t.cancelled() and t.exception():
                    raise t.exception()
        finally:
            listen_task.cancel()
            resub_task.cancel()


async def run_birdeye_ws(on_event) -> None:
    """
    Main loop: keeps the Birdeye WS connection alive with auto-reconnect.
    Calls `on_event(normalized_event)` for every incoming trade message.

    With premium API key, 403s should never occur.
    Uses exponential backoff up to MAX_RECONNECT_DELAY_SECS.
    """
    delay = RECONNECT_DELAY_SECS
    while True:
        try:
            await _run_connection(on_event)
            delay = RECONNECT_DELAY_SECS  # reset on clean disconnect
        except ConnectionClosed as exc:
            logger.warning("Birdeye WS closed (%s). Reconnecting in %ds...", exc, delay)
        except OSError as exc:
            logger.warning("Birdeye WS network error (%s). Reconnecting in %ds...", exc, delay)
        except Exception as exc:
            if "403" in str(exc):
                logger.error(
                    "Birdeye WS HTTP 403 — verify BIRDEYE_API_KEY is a valid premium key. "
                    "Retrying in %ds...", delay
                )
            else:
                logger.warning("Birdeye WS error: %s. Reconnecting in %ds...", exc, delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY_SECS)
            await asyncio.sleep(delay)
            continue

        await asyncio.sleep(delay)

