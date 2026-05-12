# Zentryx

**Real-time Solana intelligence platform for whale tracking, token analysis, signal scoring, discovery scanning, and Telegram-native execution workflows.**

Zentryx ingests on-chain activity from tracked high-performance wallets, enriches every event through a multi-source data pipeline, scores it against a proprietary multi-dimensional model, and surfaces the result across a live web dashboard and a feature-complete Telegram command center — all in under a second from chain event to alert.

---

## Table of Contents

- [What Zentryx Does](#what-zentryx-does)
- [Architecture](#architecture)
- [Product Surfaces](#product-surfaces)
- [API Reference](#api-reference)
- [WebSocket Feed](#websocket-feed)
- [Birdeye Integration](#birdeye-integration)
- [Telegram Bot](#telegram-bot)
- [Scoring Model](#scoring-model)
- [Wallet Ranking Methodology](#wallet-ranking-methodology)
- [Scheduled Jobs](#scheduled-jobs)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)

---

## What Zentryx Does

### 1 — Whale Discovery & Ranking
Zentryx continuously discovers and ranks the highest-performing Solana wallets by pulling from Birdeye's weekly PnL gainers/losers feed. Candidate wallets pass through qualification gates (positive PnL, minimum win rate, minimum trade count, active non-dust holdings) before being admitted to the tracked set. The leaderboard is refreshed weekly and served from an in-memory cache for zero-latency reads.

### 2 — Real-Time Trade Detection
Two parallel ingestion channels run concurrently to achieve complete coverage:
- **Solana RPC WebSocket** — subscribes directly to tracked wallet account activity for sub-second detection of on-chain moves.
- **Birdeye REST polling worker** — polls token transaction feeds on a short interval to catch DEX swaps that the RPC subscription may miss.

Every detected event is normalised, filtered by a minimum USD threshold, enriched with token metadata, and written to PostgreSQL. A WebSocket broadcast is then pushed to all connected frontend clients, and a formatted Telegram alert is dispatched simultaneously.

### 3 — Multi-Dimensional Token Scoring
Each token is evaluated across five independent score dimensions — Risk, Opportunity, Momentum, Liquidity, and Security — producing a composite score from 0 to 100 and a BUY / WATCH / AVOID verdict. The scoring engine is fully deterministic, requiring no external call, and runs client-side on the token detail page for instant feedback.

### 4 — AI Token Analysis
An optional Groq-powered narrative layer generates a human-readable insight paragraph per token, combining liquidity depth, price action, risk profile, and verdict reasoning into a single coherent analyst summary. The system falls back to a rule-based insight generator when the AI is unavailable, ensuring uninterrupted coverage.

### 5 — Discovery & Market Surfaces
- **Trending** — top tokens ranked by Birdeye trending score, cross-referenced against tracked whale activity.
- **New Listings** — recently launched tokens with risk flags, age metrics, and Rugcheck integration.
- **Top Movers** — 24h gainers and losers ranked by price change percentage.
- **Smart Money Heatmap** — time-bucketed view of which tokens tracked wallets are rotating into.
- **Whale Conviction Zones** — token overlap matrix identifying tokens held by 2+ tracked whales, surfaced with conviction tier (EXTREME / HIGH / MODERATE) and per-wallet allocation data.
- **Whale Rotation Detection** — identifies when tracked wallets rotate out of one token into another within a 48-hour window.

### 6 — Trader Workflow Tools
- **Paper Trading** — open virtual positions at the live Birdeye price with configurable take-profit and stop-loss percentages. Positions are tracked per Telegram user and closed automatically when TP/SL is hit or manually via command.
- **Price Alerts** — set above/below price triggers per token. A background monitor polls live prices and fires Telegram DMs when targets are reached.
- **Watchlist** — per-user token watchlist with add/remove commands and listing view.
- **Signal Scoring** — instant copy score with full factor breakdown, no AI dependency, sub-second response.

---

## Architecture

### Frontend

| Layer | Technology |
|---|---|
| Framework | Next.js (App Router, TypeScript) |
| Styling | Tailwind CSS v4 + custom design system |
| Charts | Lightweight Charts (OHLCV candlestick) |
| Real-time | Native WebSocket via custom `useWebSocket` hook |
| State | React `useState` / `useCallback` / `useEffect` — no external state library |

**Pages:**

| Route | Description |
|---|---|
| `/` | Landing page with platform overview and live stats |
| `/dashboard` | Whale leaderboard, Conviction Zones, and Rotation feed |
| `/live` | Real-time trade feed — all tracked whale moves as they happen |
| `/wallet/[address]` | Full wallet profile: PnL, win rate, trade history, portfolio X-Ray |
| `/token/[address]` | Token detail: hero card, verdict banner, AI insight, OHLCV chart, score breakdown, security flags, detected labels, and scoring signals |
| `/movers` | 24h top gainers and losers |
| `/trending` | Trending tokens with smart money cross-reference |
| `/new-listings` | New token launches with risk flags |

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI (async, Python 3.11+) |
| ORM | SQLAlchemy Async + asyncpg |
| Scheduler | APScheduler (cron + interval jobs) |
| External APIs | Birdeye (primary data), Groq (AI), Rugcheck (security) |
| Telegram | `python-telegram-bot` (command loop + outbound alerts) |
| Chain Access | Solana RPC WebSocket (Helius or public endpoint) |

**Startup sequence:**

1. Load `.env` and connect to PostgreSQL (auto-create tables if absent)
2. Start APScheduler — weekly wallet discovery + 6-hourly snapshot jobs
3. Run initial wallet discovery
4. Start Solana RPC WebSocket listener
5. Start Birdeye REST polling worker
6. Start Telegram bot command loop
7. Start price alert monitor
8. Send startup Telegram notification

### Data Layer

PostgreSQL is the single source of truth. All tables are created automatically at startup if they do not exist. Core entities:

| Table | Purpose |
|---|---|
| `wallet` | Tracked whale wallet registry with label and metadata |
| `wallet_snapshot` | Periodic PnL/trade-count snapshots per wallet for history charting |
| `trade_event` | Enriched on-chain trade events with token, USD value, and signal metadata |
| `watchlist` | Per-user token watchlists |
| `paper_trade` | Open and closed virtual positions with entry/exit prices and P&L |
| `price_alert` | Active price alert rules per user per token |
| `signal_outcome` | Historical record of signal verdicts for accuracy tracking |

---

## API Reference

All REST endpoints are prefixed with `/api`. The base URL for local development is `http://localhost:8000`.

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Returns `{"status": "ok"}`. Used by Railway and Render health checks. |

### Wallets

| Method | Endpoint | Query Params | Description |
|---|---|---|---|
| `GET` | `/api/wallets` | — | Returns the full ranked whale leaderboard. Served from in-memory cache — zero Birdeye calls, free-tier safe. Response: `[{rank, address, label, total_pnl, win_rate, trade_count}]` |
| `GET` | `/api/wallets/{address}` | — | Full wallet detail including PnL breakdown, win/loss counts, and portfolio summary fetched from Birdeye. |
| `GET` | `/api/wallets/{address}/history` | `days` (1–30, default 7) | Returns historical `WalletSnapshot` rows for PnL charting. Empty list returned gracefully when DB is unavailable. |
| `GET` | `/api/wallets/overlap` | `min_value_usd` (default 500) | Token Overlap Matrix — identifies tokens held by 2+ tracked whales. Cached for 10 minutes. Response includes conviction tiers and per-whale allocation breakdown. |
| `POST` | `/api/wallets/discover` | — | Triggers an on-demand wallet discovery run. Pulls fresh candidates from Birdeye and refreshes the in-memory leaderboard. |

### Tokens & Discovery

| Method | Endpoint | Query Params | Description |
|---|---|---|---|
| `GET` | `/api/tokens/{address}/overview` | — | Full token overview: price, 24h volume, market cap, liquidity, holder count, circulating supply, 24h price change, and Birdeye security flags (mintable, freezeable, mutable metadata, transfer fee, top-10 holder %). |
| `GET` | `/api/tokens/{address}/insight` | — | AI-generated token insight paragraph. Returns `{insight, source}` where `source` is `"groq"` or `"rule-based"`. Falls back to the rule-based engine if Groq is unavailable. |
| `GET` | `/api/tokens/{address}/ohlcv` | `timeframe` (`1D` \| `7D` \| `30D`, default `7D`) | OHLCV candlestick data from Birdeye. Returns `[{time, open, high, low, close, volume}]` with Unix timestamps. |
| `GET` | `/api/tokens/{address}/whale-buys` | — | Recent buy events for this token from tracked whale wallets. Cross-references the `trade_event` table with the tracked wallet list. |
| `GET` | `/api/tokens/{address}/mini-report` | — | Compact token snapshot used by the live feed slide-over. Includes price, 24h change, liquidity, holder count, and top signal flags. |
| `GET` | `/api/tokens/{address}/top-traders` | `limit` (default 20) | Top traders for this token by PnL over the past week (Birdeye `1W` timeframe). Flags whether each trader is a tracked whale. |
| `GET` | `/api/tokens/{address}/holders` | — | Holder distribution: total count, top-10 ownership percentage, per-holder breakdown, and concentration risk tier. |
| `GET` | `/api/tokens/{address}/trade-data` | — | 24h trade flow breakdown: buy/sell counts, buy/sell volume in USD, buy ratio, and directional pressure label (`BUY` / `SELL` / `NEUTRAL`). |
| `GET` | `/api/tokens/{address}/exit-liquidity` | — | Liquidity depth analysis: total liquidity, 1%/2% depth, per-exit-size slippage estimates, and an overall rating (`DEEP` / `ADEQUATE` / `THIN` / `CRITICAL`). |
| `GET` | `/api/movers` | — | 24h top gainers and losers from the Birdeye gainers/losers endpoint. Returns both lists with price change %, volume, and market cap. |
| `GET` | `/api/trending` | — | Trending tokens from Birdeye, enriched with tracked-whale overlap data. Each token includes a `tracked_whale_trades` array showing which whales have recently traded it. |
| `GET` | `/api/new-listings` | — | Recently launched tokens with Rugcheck security flags, age in minutes, liquidity, and holder count. |
| `GET` | `/api/heatmap` | `limit` (default 20) | Smart money activity heatmap: aggregated buy/sell volume per token across recent time buckets, showing where tracked wallets are concentrating capital. |
| `GET` | `/api/tokens/overlap` | — | Alias route for token overlap data (same as `/api/wallets/overlap`). |
| `GET` | `/api/stats/profitability` | — | Signal hit-rate and PnL accuracy statistics aggregated from the `signal_outcome` table. |

### Paper Trades

| Method | Endpoint | Body / Query Params | Description |
|---|---|---|---|
| `POST` | `/api/trades` | `{telegram_user_id, token_address, symbol, side, tp_pct, sl_pct, position_size_usd, entry_price?}` | Opens a new paper trade. Fetches the current live price from Birdeye automatically unless `entry_price` is provided. Returns the created trade record with ID. |
| `GET` | `/api/trades` | `telegram_user_id`, `status` (`open` \| `closed` \| `all`) | Lists all paper trades for a Telegram user. Returns open positions with unrealised P&L calculated against the current price, and closed positions with final outcome. |
| `PATCH` | `/api/trades/{trade_id}/close` | `{exit_price?}` | Manually closes an open paper trade. Fetches current price from Birdeye if `exit_price` is not provided. Calculates and stores final P&L percentage. |

### Price Alerts

| Method | Endpoint | Body / Query Params | Description |
|---|---|---|---|
| `POST` | `/api/alerts` | `{telegram_user_id, token_address, symbol, target_price, direction}` | Creates a new price alert. `direction` must be `"above"` or `"below"`. Alert is stored and monitored by the background price monitor service. |
| `GET` | `/api/alerts` | `telegram_user_id` | Returns all active (unfired) price alerts for a Telegram user, with token symbol and target details. |
| `DELETE` | `/api/alerts/{alert_id}` | — | Cancels and deletes a price alert by ID. Returns `204 No Content`. |

### Analytics

| Method | Endpoint | Query Params | Description |
|---|---|---|---|
| `GET` | `/api/signals/stats` | — | Aggregated signal statistics: verdict distribution (BUY/WATCH/AVOID counts), average score by verdict, and overall hit rate. Cached for performance. |
| `GET` | `/api/rotations` | `limit` (default 10) | Recent whale rotation events: cases where a tracked wallet exited one token and entered another within a 48-hour window. Includes from/to token symbols, USD values, and wallet label. |

### Live Feed (REST pre-population)

| Method | Endpoint | Query Params | Description |
|---|---|---|---|
| `GET` | `/api/trades` | `limit` (1–200, default 50), `hours` (1–720, default 24) | Fetches recent trade events from PostgreSQL for pre-populating the live feed on page load. Returns enriched events ordered by timestamp descending. |

---

## WebSocket Feed

```
WS /ws/feed
```

The live trade feed endpoint. The frontend connects here on the `/live` page and receives a continuous stream of enriched trade events as JSON objects the moment a tracked wallet makes an on-chain move.

**Event shape:**
```json
{
  "wallet_address": "AbC1...",
  "wallet_label": "Whale #3",
  "token_address": "So111...",
  "token_symbol": "BONK",
  "side": "BUY",
  "usd_value": 42000,
  "token_price": 0.00002341,
  "timestamp": "2026-05-12T09:41:00Z",
  "signal": "STRONG_BUY",
  "score": 81,
  "liquidity_usd": 1200000,
  "holders": 8420
}
```

The connection is keep-alive. The server does not send pings — the client may send any text frame to keep the connection open. On disconnect, the client is automatically removed from the broadcast pool.

---

## Birdeye Integration

The Birdeye client (`backend/services/birdeye.py`) wraps every used endpoint as a typed async method with exponential-backoff retry. All methods share a single aiohttp session for connection reuse.

| Birdeye Endpoint | Method in `birdeye.py` | Used By |
|---|---|---|
| `GET /trader/gainers-losers` | `get_gainers_losers()` | Wallet discovery, daily briefing |
| `GET /wallet/v2/pnl/summary` | `get_wallet_pnl()` | Wallet detail page, qualification filter |
| `GET /wallet/v2/net-worth` | `get_wallet_net_worth()` | Wallet snapshot service |
| `GET /v1/wallet/token_list` | `get_wallet_portfolio()` | Portfolio X-Ray tab |
| `GET /defi/token_overview` | `get_token_overview()` | Token detail, enrichment pipeline |
| `GET /defi/token_security` | `get_token_security()` | Security flags, scoring engine |
| `GET /defi/price` | `get_token_price()` | Paper trade entry/exit, price monitor |
| `GET /defi/ohlcv` | `get_token_ohlcv()` | OHLCV chart endpoint |
| `GET /defi/v3/price-stats/single` | `get_price_stats()` | Multi-timeframe price stats |
| `GET /defi/v3/token/holder` | `get_token_holders()` | Holder distribution endpoint |
| `GET /holder/v1/distribution` | `get_holder_distribution()` | Concentration breakdown |
| `GET /defi/v3/token/trade-data/single` | `get_token_trade_data()` | Trade flow endpoint |
| `GET /defi/v3/token/txs` | `get_token_txs()` | Polling worker, whale-buys lookup |
| `GET /defi/tokenlist` | `get_token_list()` | New listings enrichment |
| `GET /defi/token_trending` | `get_token_trending()` | Trending page, daily briefing |
| `GET /defi/v2/tokens/new_listing` | `get_new_listings()` | New listings page |
| `GET /defi/v2/tokens/top_traders` | `get_top_traders()` | Top traders endpoint (1W, PnL sort) |
| `GET /smart-money/v1/token/list` | `get_smart_money_tokens()` | Smart money heatmap, daily briefing |

> **Note:** `GET /wallet/v2/pnl/multiple` is implemented but disabled in the discovery path due to an inconsistent response contract observed in live usage. Single-wallet PnL calls are used instead.

---

## Telegram Bot

The bot runs as a persistent async loop (`run_bot_command_loop`) registered against the configured `TELEGRAM_BOT_TOKEN`. Commands can be sent in the configured group or directly to the bot.

### Discovery & Market Commands

| Command | Arguments | Description |
|---|---|---|
| `/trending` | — | Top 5 trending tokens from Birdeye with 24h price change and market cap. |
| `/new-listings` | — | 5 most recently launched tokens with risk flags, age, and liquidity. |
| `/holdings` | `<token_address>` | Shows which tracked whale wallets currently hold the specified token. |

### Token Analysis Commands

| Command | Arguments | Description |
|---|---|---|
| `/signal` | `<token_address>` | Instant copy score with full 6-factor breakdown (Risk, Opportunity, Momentum, Liquidity, Security, Composite). No AI dependency — sub-second response. Verdict: `COPY` / `WATCH` / `SKIP`. |
| `/analyze` | `<token_address>` | Full Groq AI analysis. Returns a BUY / HOLD / AVOID recommendation with a detailed narrative paragraph. Response time ~15–25s depending on Groq load. |

### Paper Trading Commands

| Command | Arguments | Description |
|---|---|---|
| `/track` | `<token_address> [tp%] [sl%]` | Opens a paper trade at the current live price. Example: `/track BONK 40 15` sets a 40% take-profit and 15% stop-loss. |
| `/my-trades` | — | Lists all open and recently closed paper trades for your Telegram user ID, with live unrealised P&L for open positions. |
| `/close-trade` | `<trade_id>` | Manually closes an open paper trade at the current price. Outputs final P&L percentage. |

### Price Alert Commands

| Command | Arguments | Description |
|---|---|---|
| `/alert` | `<token_address> <price> <above\|below>` | Sets a price alert. Fires a Telegram DM when the token crosses the target. Example: `/alert SOL 200 above`. |
| `/my-alerts` | — | Lists all your active (unfired) price alerts. |
| `/cancel-alert` | `<alert_id>` | Cancels a price alert by ID. The ID is shown in `/my-alerts` output. |

### Watchlist Commands

| Command | Arguments | Description |
|---|---|---|
| `/watch` | `<token_address>` | Adds a token to your personal watchlist. |
| `/unwatch` | `<token_address>` | Removes a token from your watchlist. |
| `/my-wallets` | — | Lists all tokens on your watchlist. |

### Wallet & Stats Commands

| Command | Arguments | Description |
|---|---|---|
| `/wallets` | — | Shows the top 5 whales from the leaderboard with PnL and win rate. |
| `/wallet` | `<address>` | Pulls a summary of any Solana wallet — PnL, win rate, and trade count. |
| `/stats` | — | Platform-level stats: total tracked wallets, 7D combined PnL, signal hit rate. |
| `/top` | — | Top 3 performing wallets of the current week. |
| `/filter` | `<min_pnl> <min_wr>` | Filters the leaderboard by minimum PnL and win-rate thresholds. |

### Utility Commands

| Command | Arguments | Description |
|---|---|---|
| `/start` | — | Welcome message and quick-start guide. |
| `/help` | — | Full command reference list. |
| `/test_alert` | — | Sends a test alert to confirm the bot is connected and messaging correctly. |

### Daily Alpha Briefing

At **09:00 UTC** every day, the bot automatically sends a Daily Alpha Briefing to the configured group channel. The briefing includes:

- **Whale Activity (24h)** — DB-sourced top whale moves from the past 24 hours.
- **Smart Money Radar** — top 3 tokens that smart-money wallets are accumulating (from Birdeye smart-money feed).
- **Trending Now** — top 3 tokens by Birdeye trending rank with 24h price change.
- **Top Gainer Wallet** — the single best-performing wallet in the past 24h from the gainers/losers feed.
- **Best Signal** — the highest-scoring token signal from the cached signal stats.
- **AI Insight** — a Groq-generated summary of the overall market posture for the day (gracefully omitted if Groq is unavailable).

All three Birdeye calls in the briefing run in parallel via `asyncio.gather` — a single API failure does not block the rest of the briefing from sending.

---

## Scoring Model

The scoring engine (`scoreToken` in `app/token/[address]/page.tsx`) runs entirely client-side and produces five independent dimension scores (0–100) plus a composite.

| Dimension | Weight | Inputs |
|---|---|---|
| Risk | 30% | Holder count, token age, 24h price change, security score, liquidity/MC ratio |
| Opportunity | 25% | Market cap tier, token age vs risk score, opportunity penalty for high risk |
| Momentum | 20% | 24h price change %, 24h volume, volume change vs prior day, price + volume confirmation |
| Liquidity | 15% | Absolute liquidity (log-scaled), liquidity-to-market-cap ratio |
| Security | 10% | Birdeye security flags (mintable, freezeable, mutable metadata, transfer fee), top-10 holder concentration |

**Verdict logic:**
- `AVOID` — security score < 25 or risk score < 20
- `BUY` — strong across risk, security, opportunity, and momentum, or composite ≥ 72 with adequate liquidity, or confirmed breakout on a safe token
- `WATCH` — everything else; sub-reasons are generated from the active dimension scores

Up to 18 human-readable **labels** are attached to each token (e.g. `price-breakout`, `low-liquidity`, `mintable`, `volume-spike`) and all contributing **signals** are listed individually with their delta contribution and category.

---

## Wallet Ranking Methodology

Candidate wallets are seeded from Birdeye's `gainers-losers` endpoint using a 1-week timeframe sorted by PnL. The following qualification gates are applied before a wallet enters the tracked set:

| Filter | Condition |
|---|---|
| Profitability | `total_pnl > 0` |
| Win rate | `win_rate ≥ minimum threshold` (configurable) |
| Trade count | `trade_count ≥ minimum threshold` (configurable) |
| Activity | Must hold at least one non-dust position |

Qualified wallets are ranked by total PnL descending and labelled `Whale #1`, `Whale #2`, etc. Rankings are persisted to PostgreSQL and served from an in-memory cache for zero-latency leaderboard reads.

**Important:** Zentryx tracks a high-signal, PnL-qualified cohort — not an exhaustive global ranking of all Solana addresses. Birdeye caps the candidate pool per call; this is a deliberate tradeoff between API efficiency and coverage breadth.

---

## Scheduled Jobs

| Job | Schedule | Description |
|---|---|---|
| Wallet Discovery | Weekly (Monday 00:00 UTC) | Re-runs the full discovery pipeline and refreshes the leaderboard. |
| Wallet Snapshots | Every 6 hours | Saves a PnL/trade-count snapshot for every tracked wallet, enabling history charts. |
| Daily Briefing | Daily 09:00 UTC | Sends the enriched alpha briefing to the configured Telegram group. |
| Price Monitor | Continuous (30s poll) | Checks active price alerts against live Birdeye prices and fires DMs when targets are hit. Also evaluates open paper trade TP/SL. |

---

## Getting Started

### Prerequisites

| Requirement | Version |
|---|---|
| Node.js | 18+ |
| Python | 3.11+ |
| PostgreSQL | 14+ |
| Birdeye API key | Premium tier (for security, holder, trade-data endpoints) |
| Telegram bot token | From [@BotFather](https://t.me/BotFather) |
| Groq API key | Optional — enables AI insight and daily briefing narrative |

### Frontend

```bash
npm install
npm run dev        # http://localhost:3000
```

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

### Running Tests

```bash
cd backend
.venv\Scripts\python.exe -m pytest test_telegram_bot.py -v
```

The test suite covers all 6 Telegram bot feature areas (41 tests). All external dependencies are mocked — no live API calls or database connection required.

---

## Environment Variables

Create `backend/.env` with the following keys:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (`postgresql+asyncpg://user:pass@host/db`) |
| `BIRDEYE_API_KEY` | Yes | Birdeye API key (premium tier recommended) |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_GROUP_ID` | Yes | Numeric group/channel ID for outbound alerts and briefings |
| `GROQ_API_KEY` | No | Enables Groq AI analysis and daily briefing narrative |
| `HELIUS_API_KEY` | No | Helius RPC endpoint for WebSocket trade detection (falls back to public RPC) |
| `SOLANA_RPC_URL` | No | Custom RPC WebSocket URL override |
| `NEXT_PUBLIC_API_URL` | No | Frontend API base URL (defaults to `http://localhost:8000`) |

## 1. Install Frontend Dependencies

From repository root:

```bash
npm install
```

Create .env.local in the repository root:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

## 2. Install Backend Dependencies

```bash
cd backend
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install packages:

```bash
pip install -r requirements.txt
```

Create backend/.env:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
BIRDEYE_API_KEY=your_birdeye_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_default_chat_id
GROQ_API_KEY=your_groq_api_key
```

Optional values:

```env
TELEGRAM_GROUP_CHAT_ID=your_group_chat_id
FRONTEND_URL=http://localhost:3000
SOLANA_RPC_WS_URL=wss://api.mainnet-beta.solana.com
```

## 3. Run the Backend

From backend directory:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Or from repository root on Windows:

```powershell
& ".\backend\.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir ".\backend"
```

## 4. Run the Frontend

From repository root:

```bash
npm run dev
```

Frontend: http://localhost:3000
Backend: http://localhost:8000

## 5. Verify

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status":"ok","service":"zentryx-api","version":"0.2.0"}
```

## Operations Notes

- Startup includes wallet discovery, scheduler bootstrap, Telegram command loop, and price monitor task.
- If you change backend routes/services, restart uvicorn to avoid stale runtime behavior.
- Discovery currently uses per-wallet /wallet/v2/pnl/summary calls for reliability in production.
- AI insights are additive: platform remains functional without Groq responses.

## Deployment

The repository includes render.yaml for backend deployment workflows and is compatible with standard Next.js frontend hosting.

Production checklist:
- Set all environment variables in hosting platform
- Use wss:// for NEXT_PUBLIC_WS_URL in production
- Restrict CORS FRONTEND_URL to your deployed frontend origin
- Ensure long-running backend process for scheduler + bot loop

## License

MIT
