"""
Zentryx Background Worker — always-on monitoring process.

Runs independently of the FastAPI web service so Render's free-tier
spindown (triggered by HTTP inactivity) never kills the monitors.

Responsibilities:
  1. Connect to PostgreSQL
  2. Start APScheduler (weekly wallet discovery + 6-hourly snapshots + daily TTL cleanup)
  3. Run initial wallet discovery on startup
  4. Start Solana RPC WebSocket listener (real-time whale trade detection)
  5. Start Telegram bot command loop
  6. Send Telegram startup notification
  7. Keep running forever — exits only on SIGINT / SIGTERM
"""
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import db
from scheduler import scheduler
from services.enrichment import process_trade_event
from services.solana_rpc_ws import run_solana_rpc_ws
from services.telegram import run_bot_command_loop, send_startup_message
from services.wallet_discovery import discover_wallets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Zentryx worker starting up...")

    await db.connect()

    scheduler.start()
    logger.info("Scheduler started. Running initial wallet discovery...")
    await discover_wallets()

    ws_task = asyncio.create_task(run_solana_rpc_ws(process_trade_event))
    logger.info("Solana RPC WebSocket listener started.")

    bot_task = asyncio.create_task(run_bot_command_loop())
    logger.info("Telegram bot command loop started.")

    await send_startup_message()
    logger.info("Worker startup complete — monitoring for whale trades.")

    # ── Run until cancelled (SIGINT / SIGTERM) ──────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await stop_event.wait()

    # ── Graceful shutdown ───────────────────────────────────────────────────
    logger.info("Zentryx worker shutting down...")
    ws_task.cancel()
    bot_task.cancel()
    await asyncio.gather(ws_task, bot_task, return_exceptions=True)
    scheduler.shutdown(wait=False)
    await db.disconnect()
    logger.info("Zentryx worker shut down.")


if __name__ == "__main__":
    asyncio.run(main())
