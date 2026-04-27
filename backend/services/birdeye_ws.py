"""
Birdeye WebSocket client — subscribes to per-wallet trade streams and
large-trade alerts, then pipes events into the enrichment pipeline.

Protocol: wss://public-api.birdeye.so/socket?x-api-key=KEY
Messages follow the Birdeye WS message spec:
  { "type": "SUBSCRIBE_WALLET_TXS", "data": { "wallet": "<address>" } }
  { "type": "SUBSCRIBE_LARGE_TRADE_TXS", "data": { "min_volume": 10000 } }
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

BIRDEYE_WS_URL = "wss://public-api.birdeye.so/socket"
RECONNECT_DELAY_SECS = 5
MAX_RECONNECT_DELAY_SECS = 300  # 5 minutes cap
LARGE_TRADE_MIN_VOLUME = 10_000  # USD


def _build_subscribe_wallet(address: str) -> str:
    return json.dumps({"type": "SUBSCRIBE_WALLET_TXS", "data": {"wallet": address}})


def _build_subscribe_large_trades() -> str:
    return json.dumps(
        {"type": "SUBSCRIBE_LARGE_TRADE_TXS", "data": {"min_volume": LARGE_TRADE_MIN_VOLUME}}
    )


async def _run_connection(on_event) -> None:
    """Single WebSocket connection attempt. Subscribes to all tracked wallets."""
    from services.wallet_discovery import tracked_wallets  # import here to get live state

    api_key = os.getenv("BIRDEYE_API_KEY", "")

    # Birdeye WS: pass API key as a header and chain as a header
    extra_headers = {
        "x-api-key": api_key,
        "x-chain": "solana",
    }

    logger.info("Connecting to Birdeye WebSocket...")
    async with websockets.connect(
        BIRDEYE_WS_URL,
        additional_headers=extra_headers,
        ping_interval=20,
        ping_timeout=10,
    ) as ws:
        logger.info("Birdeye WS connected.")

        # Subscribe to each tracked wallet
        wallet_addresses = list(tracked_wallets.keys())
        for address in wallet_addresses:
            await ws.send(_build_subscribe_wallet(address))
            logger.info("Subscribed to wallet txs: %s", address[:8] + "...")

        # Subscribe to large trades (whale alerts)
        await ws.send(_build_subscribe_large_trades())
        logger.info("Subscribed to large trades (min $%s).", LARGE_TRADE_MIN_VOLUME)

        # Listen loop
        async for raw in ws:
            try:
                payload: dict[str, Any] = json.loads(raw)
                await on_event(payload)
            except json.JSONDecodeError:
                logger.warning("Non-JSON WS message: %s", raw[:200])
            except Exception as exc:
                logger.exception("Error handling WS event: %s", exc)


async def run_birdeye_ws(on_event) -> None:
    """
    Main loop that keeps the Birdeye WS connection alive with auto-reconnect.
    Call `on_event(payload)` for every incoming message.

    On HTTP 403, logs a single clear warning about plan tier and backs off
    to the maximum delay — the REST polling fallback will handle live data.
    """
    delay = RECONNECT_DELAY_SECS
    while True:
        try:
            await _run_connection(on_event)
            delay = RECONNECT_DELAY_SECS  # reset on clean run
        except ConnectionClosed as exc:
            logger.warning("Birdeye WS closed (%s). Reconnecting in %ds...", exc, delay)
        except OSError as exc:
            logger.warning("Birdeye WS network error (%s). Reconnecting in %ds...", exc, delay)
        except Exception as exc:
            # Detect 403 plan-restriction specifically
            if "403" in str(exc):
                logger.warning(
                    "Birdeye WebSocket: HTTP 403 — WebSocket access requires a paid API plan.\n"
                    "Live data will be served via REST polling fallback instead."
                )
                delay = MAX_RECONNECT_DELAY_SECS  # back off fully, don't hammer
            else:
                logger.warning("Birdeye WS error: %s. Reconnecting in %ds...", exc, delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY_SECS)

        await asyncio.sleep(delay)
