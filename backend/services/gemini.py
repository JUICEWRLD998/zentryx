"""
AI analysis client — Groq (llama-3.3-70b-versatile, free tier: 14,400 RPD).

Design decisions:
  - Uses groq Python SDK (sync client, run in thread pool for async compat).
  - One shared Groq client instance per process.
  - Falls back to None silently — the pipeline never blocks on AI.
  - Semaphore-limited to 1 concurrent call; 2s min interval between calls.

Called from enrichment.py AFTER TokenMiniReport is built so the prompt
has full context (price, security score, smart money flag, etc.).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

# Shared client (lazy-initialised)
_client = None
_client_lock = asyncio.Lock()

# Cap at 1 concurrent Groq call
_groq_sem = asyncio.Semaphore(1)

# 2s min interval → well under 30 RPM free-tier limit
_last_call_ts: float = 0.0
_MIN_INTERVAL_S: float = 2.0

# Groq model — llama-3.3-70b is fast and free
_MODEL_NAME = "llama-3.3-70b-versatile"


async def _get_client():
    """Return (or lazily init) the Groq client."""
    global _client
    if _client is not None:
        return _client

    async with _client_lock:
        if _client is not None:
            return _client
        try:
            from groq import Groq  # type: ignore

            api_key = os.getenv("GROQ_API_KEY", "")
            if not api_key:
                logger.warning("GROQ_API_KEY not set — AI analysis disabled.")
                return None
            _client = Groq(api_key=api_key)
            logger.info("Groq client initialised: %s", _MODEL_NAME)
        except Exception as exc:
            logger.warning("Groq init failed: %s", exc)
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
    honeypot_str = "YES — AVOID" if is_honeypot else ("No" if is_honeypot is not None else "Unknown")
    momentum_str = f"{momentum_24h:+.1f}%" if momentum_24h is not None else "N/A"
    sec_str = f"{security_score:.0f}/100" if security_score is not None else "N/A"
    bsr_str = f"{buy_sell_ratio:.2f}" if buy_sell_ratio is not None else "N/A"
    liq_str = f"${liquidity_usd:,.0f}" if liquidity_usd is not None else "N/A"
    mc_str = f"${market_cap:,.0f}" if market_cap is not None else "N/A"
    copy_str = f"{copy_score:.0f}/100" if copy_score is not None else "N/A"
    consensus_str = f"{consensus_count} whale wallet(s) bought in last 2h" if consensus_count > 0 else "None"

    return f"""You are a concise Solana on-chain analyst. A whale just made a notable trade.
Analyse the data and respond in exactly this JSON format (no markdown, no extra text):
{{"recommendation": "STRONG_BUY | BUY | HOLD | SELL | AVOID", "analysis": "Your 2-3 sentence analysis."}}

=== TRADE ===
Token: {token_symbol} ({token_address[:8]}...)
Side: {side}  |  Size: ${usd_value:,.0f}

=== TOKEN INTELLIGENCE ===
Security: {sec_str}  |  Honeypot: {honeypot_str}  |  Smart Money: {{"YES" if smart_money_flag else "No"}}
24h Momentum: {momentum_str}  |  Holders: {holder_count or "N/A"}  |  Buy/Sell Ratio: {bsr_str}
Liquidity: {liq_str}  |  Market Cap: {mc_str}
Copy Score: {copy_str}  |  Whale Consensus: {consensus_str}

Be direct. Synthesise the signals — do NOT repeat raw numbers. Highlight the single most important factor."""


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
    Run a Groq AI analysis for a single trade event.

    Returns {"recommendation": str, "analysis": str} or None on any error.
    """
    global _last_call_ts

    client = await _get_client()
    if client is None:
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

    async with _groq_sem:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a concise Solana on-chain trading analyst. Always respond with valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=256,
                ),
            )
            _last_call_ts = time.monotonic()

            import json
            raw_text = response.choices[0].message.content.strip()

            # Strip markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            raw_text = raw_text.strip()

            result: dict = json.loads(raw_text)
            rec = str(result.get("recommendation", "HOLD")).upper()
            analysis = str(result.get("analysis", ""))
            if rec not in ("STRONG_BUY", "BUY", "HOLD", "SELL", "AVOID"):
                rec = "HOLD"

            logger.info("Groq: %s %s → %s", token_symbol, side, rec)
            return {"recommendation": rec, "analysis": analysis}

        except Exception as exc:
            logger.warning("Groq analysis failed for %s: %s", token_symbol, exc)
            _last_call_ts = time.monotonic()
            return None


async def analyse_daily_briefing(data: dict) -> str | None:
    """
    Generate a market-wide narrative insight for the daily briefing.

    Receives the aggregated 24h briefing data dict and returns a 3-4 sentence
    prose string, or None on any error (briefing still sends without AI section).
    """
    global _last_call_ts

    client = await _get_client()
    if client is None:
        return None

    # Build a compact context string for the prompt
    acc_lines = "\n".join(
        f"  - ${t['symbol']}: {t['wallet_count']} whale wallet(s), ${t['total_usd']:,.0f} combined"
        for t in data.get("accumulation_tokens", [])
    ) or "  (none)"
    exit_lines = "\n".join(
        f"  - ${t['symbol']}: {t['wallet_count']} wallet(s) exiting, ${t['total_usd']:,.0f} total"
        for t in data.get("exit_tokens", [])
    ) or "  (none)"

    context = (
        f"LAST 24H WHALE SUMMARY\n"
        f"Total trades: {data.get('total_trades', 0)} "
        f"({data.get('buy_count', 0)} BUYs / {data.get('sell_count', 0)} SELLs)\n"
        f"Total notional volume: ${data.get('total_volume_usd', 0):,.0f}\n\n"
        f"Smart money accumulation (top tokens by wallet count):\n{acc_lines}\n\n"
        f"Smart money exits (top tokens):\n{exit_lines}"
    )

    system_msg = (
        "You are a concise Solana on-chain market analyst writing a daily briefing. "
        "Given the whale trading summary, write 3-4 sentences of market insight. "
        "Focus on patterns, rotation themes, and what the consensus signals suggest. "
        "Be direct and specific. Do NOT use bullet points. Plain prose only."
    )

    async with _groq_sem:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": context},
                    ],
                    temperature=0.4,
                    max_tokens=200,
                ),
            )
            _last_call_ts = time.monotonic()
            insight = response.choices[0].message.content.strip()
            logger.info("Daily briefing AI insight generated (%d chars)", len(insight))
            return insight

        except Exception as exc:
            logger.warning("Daily briefing Groq call failed: %s", exc)
            _last_call_ts = time.monotonic()
            return None


async def analyse_token_overview(
    *,
    token_symbol: str,
    token_address: str,
    price: float,
    price_change_24h: float,
    volume_24h_usd: float,
    market_cap: float,
    liquidity: float,
    holders: int,
    security_score: float | None,
    flags: dict[str, object] | None = None,
) -> str | None:
    """
    Generate a concise AI insight paragraph for the token detail page.

    Returns a 2-3 sentence paragraph or None if Groq is unavailable.
    """
    global _last_call_ts

    client = await _get_client()
    if client is None:
        return None

    flags = flags or {}
    score_str = f"{security_score:.0f}/100" if security_score is not None else "N/A"
    prompt = (
        "You are a concise Solana token analyst. "
        "Write exactly 2-3 sentences in plain prose with no markdown and no bullet points. "
        "Give a practical trading risk/reward view using the metrics below.\n\n"
        f"Token: {token_symbol} ({token_address[:8]}...)\n"
        f"Price: ${price:,.8f}\n"
        f"24h change: {price_change_24h:+.2f}%\n"
        f"24h volume: ${volume_24h_usd:,.0f}\n"
        f"Market cap: ${market_cap:,.0f}\n"
        f"Liquidity: ${liquidity:,.0f}\n"
        f"Holders: {holders:,}\n"
        f"Security score: {score_str}\n"
        f"Security flags: {flags}\n\n"
        "Focus on the single most important bullish factor and single most important risk factor."
    )

    async with _groq_sem:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a concise Solana on-chain analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.35,
                    max_tokens=220,
                ),
            )
            _last_call_ts = time.monotonic()
            insight = response.choices[0].message.content.strip()
            return insight or None
        except Exception as exc:
            logger.warning("Groq token-overview analysis failed for %s: %s", token_symbol, exc)
            _last_call_ts = time.monotonic()
            return None


