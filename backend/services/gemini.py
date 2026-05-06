"""
Gemini AI client — async wrapper around google-genai (new SDK).

Design decisions:
  - Uses gemini-1.5-flash (generous free tier: 1500 RPD, 15 RPM).
  - One shared client instance per process (thread-safe).
  - Falls back to None silently — the pipeline never blocks on AI.
  - Rate-limited to 1 concurrent call to stay well under 15 RPM.

Called from enrichment.py AFTER TokenMiniReport is built so the prompt
has full context (price, security score, smart money flag, etc.).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Shared client instance (lazy-initialised)
_client = None
_client_lock = asyncio.Lock()

# Semaphore: cap at 1 concurrent Gemini call so we never burn through quota
_gemini_sem = asyncio.Semaphore(1)

# Simple in-process rate limiter: 1 req/5s → well under 15 RPM
_last_call_ts: float = 0.0
_MIN_INTERVAL_S: float = 5.0

# Model name — gemini-2.0-flash: available on this key, requires billing
_MODEL_NAME = "gemini-2.0-flash"


async def _get_client():
    """Return (or lazily init) the Gemini client, handling import errors gracefully."""
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client
        try:
            from google import genai  # type: ignore

            api_key = os.getenv("GEMINI_API_KEY", "")
            if not api_key:
                logger.warning("GEMINI_API_KEY not set — AI analysis disabled.")
                return None
            _client = genai.Client(api_key=api_key)
            logger.info("Gemini client initialised: %s", _MODEL_NAME)
        except Exception as exc:
            logger.warning("Gemini init failed: %s", exc)
            _client = None
    return _client


def _build_prompt(
    *,
    token_symbol: str,
    token_address: str,
    side: str,
    usd_value: float,
    security_score: float | None,
    is_honeypot: bool | None,
    smart_money_flag: bool,
    momentum_24h: float | None,
    holder_count: int | None,
    buy_sell_ratio: float | None,
    liquidity_usd: float | None,
    market_cap: float | None,
    copy_score: float | None,
    consensus_count: int,
) -> str:
    """
    Build a compact, structured prompt for Gemini.
    Keeps token count low — answer is short by design.
    """
    honeypot_str = "YES — AVOID" if is_honeypot else ("No" if is_honeypot is not None else "Unknown")
    momentum_str = f"{momentum_24h:+.1f}%" if momentum_24h is not None else "N/A"
    sec_str = f"{security_score:.0f}/100" if security_score is not None else "N/A"
    bsr_str = f"{buy_sell_ratio:.2f}" if buy_sell_ratio is not None else "N/A"
    liq_str = f"${liquidity_usd:,.0f}" if liquidity_usd is not None else "N/A"
    mc_str = f"${market_cap:,.0f}" if market_cap is not None else "N/A"
    copy_str = f"{copy_score:.0f}/100" if copy_score is not None else "N/A"
    consensus_str = f"{consensus_count} whale wallet(s) bought in last 2h" if consensus_count > 0 else "None"

    return f"""You are a concise Solana on-chain analyst. A whale just made a notable trade.
Analyse the data below and provide a ONE-SENTENCE recommendation and a SHORT 2-3 sentence analysis.

=== TRADE ===
Token: {token_symbol} ({token_address[:8]}...)
Side: {side}
Trade Size: ${usd_value:,.0f}

=== TOKEN INTELLIGENCE ===
Security Score: {sec_str}
Honeypot: {honeypot_str}
Smart Money Flag: {"YES" if smart_money_flag else "No"}
24h Momentum: {momentum_str}
Holder Count: {holder_count or "N/A"}
Buy/Sell Ratio: {bsr_str}  (>0.5 = more buying than selling)
Liquidity: {liq_str}
Market Cap: {mc_str}
Copy Score: {copy_str}  (how reliably copying this whale has been profitable)
Whale Consensus: {consensus_str}

=== TASK ===
Respond in exactly this JSON format (no markdown, no extra text):
{{"recommendation": "STRONG_BUY | BUY | HOLD | SELL | AVOID", "analysis": "Your 2-3 sentence analysis here."}}

Be direct. Focus on what matters most for a trader deciding whether to copy this trade.
Highlight any red flags or strong confirmations. Do NOT repeat the raw numbers — synthesise them."""


async def analyse_trade(
    *,
    token_symbol: str,
    token_address: str,
    side: str,
    usd_value: float,
    security_score: float | None,
    is_honeypot: bool | None,
    smart_money_flag: bool,
    momentum_24h: float | None,
    holder_count: int | None,
    buy_sell_ratio: float | None,
    liquidity_usd: float | None,
    market_cap: float | None,
    copy_score: float | None,
    consensus_count: int,
) -> dict[str, str] | None:
    """
    Run a Gemini analysis for a single trade event.

    Returns a dict with keys:
      "recommendation" → one of STRONG_BUY / BUY / HOLD / SELL / AVOID
      "analysis"       → 2-3 sentence plain English analysis

    Returns None on any error so callers can degrade gracefully.
    """
    global _last_call_ts

    model = await _get_client()
    if model is None:
        return None

    prompt = _build_prompt(
        token_symbol=token_symbol,
        token_address=token_address,
        side=side,
        usd_value=usd_value,
        security_score=security_score,
        is_honeypot=is_honeypot,
        smart_money_flag=smart_money_flag,
        momentum_24h=momentum_24h,
        holder_count=holder_count,
        buy_sell_ratio=buy_sell_ratio,
        liquidity_usd=liquidity_usd,
        market_cap=market_cap,
        copy_score=copy_score,
        consensus_count=consensus_count,
    )

    async with _gemini_sem:
        # Enforce minimum interval between calls
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)

        try:
            from google import genai  # type: ignore

            # google-genai is not natively async — run in thread pool
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model.models.generate_content(
                    model=_MODEL_NAME,
                    contents=prompt,
                ),
            )
            _last_call_ts = time.monotonic()

            raw_text = response.text.strip()

            # Parse the JSON response
            import json
            # Strip markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            result: dict[str, Any] = json.loads(raw_text.strip())

            # Validate expected keys
            rec = str(result.get("recommendation", "HOLD")).upper()
            analysis = str(result.get("analysis", ""))
            if rec not in ("STRONG_BUY", "BUY", "HOLD", "SELL", "AVOID"):
                rec = "HOLD"

            logger.info(
                "Gemini: %s %s → %s", token_symbol, side, rec
            )
            return {"recommendation": rec, "analysis": analysis}

        except Exception as exc:
            logger.warning("Gemini analysis failed for %s: %s", token_symbol, exc)
            _last_call_ts = time.monotonic()  # still count as a call
            return None
