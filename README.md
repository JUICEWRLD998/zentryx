# Zentryx — Solana Whale Intelligence Terminal

> Real-time on-chain whale tracking, copy-trading signals, and Telegram alerts powered by Solana RPC WebSocket and Birdeye API.

Zentryx automatically discovers the top-performing wallets on Solana, tracks their trades as they hit the blockchain, enriches each event with deep token intelligence, and persists everything to PostgreSQL for historical analysis. Alerts are delivered instantly to your Telegram inbox — and the full trading picture is visualised through a live, WebSocket-powered dashboard.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Database Schema](#database-schema)
- [Birdeye API Endpoints](#birdeye-api-endpoints)
- [REST API Reference](#rest-api-reference)
- [Telegram Bot](#telegram-bot)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Quota & Cost Optimisation](#quota--cost-optimisation)
- [Deployment](#deployment)
- [Future Improvements](#future-improvements)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **Whale Leaderboard** | Top-performing Solana wallets ranked by 7-day PnL, win rate, and trade count |
| **Live Trade Feed** | Real-time trade stream via WebSocket; REST polling fallback for free-tier compatibility |
| **Whale Profiles** | Per-wallet detail page with historical PnL snapshots, net worth, and trade history |
| **Token Intelligence** | Security scoring, honeypot detection, smart money signals, liquidity, and momentum per token |
| **PostgreSQL Persistence** | Wallets, 6-hour snapshots, 30-day trade events, and watchlists stored in Prisma Cloud |
| **Telegram Bot** | 10 commands covering leaderboard, stats, alerts, and personal watchlists |
| **Personal Watchlists** | Users subscribe to specific wallets and receive DM alerts on every $2,000+ trade |
| **Startup Notification** | Bot sends a ping on every backend boot (0 compute units) |
| **Dark / Light Mode** | Terminal-aesthetic dark default with a clean light-mode toggle |

---

## Tech Stack

### Frontend

| Library | Version | Purpose |
|---|---|---|
| Next.js | 16.2.4 | App Router, TypeScript, SSR/SSG |
| Tailwind CSS | v4 | Utility-first styling with custom Zentryx theme |
| Framer Motion | latest | Page and card animations |
| Recharts | latest | PnL charts, pie charts, radial gauges |
| Lucide React | latest | Icon set |
| next-themes | latest | Dark / light mode toggle |
| shadcn/ui | latest | Accessible UI component primitives |

### Backend

| Library | Version | Purpose |
|---|---|---|
| FastAPI | latest | Async REST API and WebSocket server |
| Uvicorn | latest | ASGI server |
| Prisma Client Python | 0.15.0 | Type-safe async PostgreSQL ORM |
| APScheduler | latest | Cron jobs (wallet discovery, snapshots, TTL cleanup) |
| python-telegram-bot | latest | Bot commands and DM alerts |
| httpx | latest | Async HTTP client for Birdeye with exponential-backoff retry |
| Pydantic v2 | latest | Request / response schema validation |

### Infrastructure

| Service | Role |
|---|---|
| PostgreSQL (Prisma Cloud) | Persistent storage — wallets, snapshots, trades, watchlists, cache |
| Solana RPC (mainnet-beta) | Real-time whale trade detection via `accountSubscribe` WebSocket |
| Birdeye API (free tier) | Token intelligence — security scoring, honeypot flags, market metrics |
| Telegram Bot API | Command handling and real-time DM alerts |

---

## Architecture Overview

```
+-----------------------------------------------------------------+
|                        Next.js Frontend                         |
|  /          /dashboard    /live      /wallet/[addr]             |
|  Landing    Leaderboard   Live Feed  Whale Detail               |
+----------------------------+------------------------------------+
                             |  REST + WebSocket
+----------------------------v------------------------------------+
|                       FastAPI Backend                           |
|                                                                 |
|  +-----------------+  +-----------+  +---------+  +----------+  |
|  | Solana RPC WS   |  | Polling   |  | APSched |  | Telegram | |
|  | (real-time)     |  | Worker    |  | uler    |  | Bot      | |
|  | accountSubscribe|  | (fallback)|  | (mgmt)  |  | (cmds)   | |
|  | 3 wallets       |  | 20-min    |  |         |  |          | |
|  |                 |  | interval  |  | Discover| /watchlist |
|  |                 |  |           |  | Snapshot| /alert DMs |
|  |                 |  |           |  | Cleanup | +----------+  |
|  +--------+--------+  +-----+-----+  +----+----+                |
|           |                |             |                     |
|           +----------------+-------------+                     |
|                    |                                            |
|        +----------v------------------------------------------+  |
|        |  Trade Enrichment Pipeline                        |  |
|        |  1. Validate & filter (amount >= $2,000)          |  |
|        |  2. Enrich with Birdeye (security, honeypot)      |  |
|        |  3. Persist TradeEvent (dedup by signature)       |  |
|        |  4. Broadcast via WebSocket manager               |  |
|        |  5. Fire Telegram watchlist DMs                   |  |
|        +------------------------------------------+--------+  |
+-----------------------------------------------------------------+
                             |
+----------------------------v------------------------------------+
|                  PostgreSQL (Prisma Cloud)                      |
|  wallet  wallet_snapshot  trade_event  user_watchlist           |
|  smart_money_cache  token_enrichment_cache                      |
+-----------------------------------------------------------------+
```

### Startup Sequence

1. Load `backend/.env` (CWD-independent via `Path(__file__).parent`)
2. Connect to PostgreSQL via Prisma
3. Start APScheduler (3 jobs registered)
4. Run initial wallet discovery via Birdeye (populates DB on first boot)
5. Launch **Solana RPC WebSocket listener** (primary real-time trade detection)
6. Launch REST polling worker (secondary fallback, 20-min interval)
7. Launch Telegram bot command loop
8. Send Telegram startup notification (0 CU)

---

## Database Schema

Six tables managed by Prisma ORM, synced via `prisma db push`.

### `wallet`
Tracked whale wallets. Top 15 refreshed weekly by APScheduler.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `address` | String (unique) | Solana wallet address |
| `label` | String | Human-readable label (e.g. "Whale #1") |
| `win_rate` | Float | Win rate as a percentage |
| `total_pnl` | Float | Total realised + unrealised PnL (USD) |
| `trade_count` | Int | Total trades in the tracked period |
| `created_at` | DateTime | First seen timestamp |
| `updated_at` | DateTime | Last upsert timestamp |

### `wallet_snapshot`
6-hour historical metric captures used for PnL charting. Index on `(wallet_id, timestamp DESC)`.

| Column | Type | Description |
|---|---|---|
| `wallet_id` | UUID (FK) | References `wallet.id` |
| `timestamp` | DateTime | Snapshot capture time |
| `total_pnl` | Float | Total PnL at this point in time |
| `realized_pnl` | Float? | Realised PnL |
| `unrealized_pnl` | Float? | Unrealised PnL |
| `win_rate` | Float | Win rate at this point in time |
| `trade_count` | Int | Cumulative trades |
| `net_worth_usd` | Float? | Portfolio net worth |

### `trade_event`
Live trade log with 30-day rolling TTL. Deduplicated by on-chain `signature`.

| Column | Type | Description |
|---|---|---|
| `signature` | String (unique) | On-chain transaction signature |
| `wallet_id` | UUID? (FK) | Linked tracked wallet (nullable) |
| `token_address` | String | Token mint address |
| `token_symbol` | String? | Token ticker (e.g. "SOL") |
| `side` | Enum BUY/SELL/UNKNOWN | Trade direction |
| `usd_value` | Float | Trade size in USD |
| `security_score` | Float? | Token security score (0–100) |
| `is_honeypot` | Boolean? | Honeypot detection flag |
| `smart_money_flag` | Boolean | True if token is on smart-money list |
| `momentum_24h` | Float? | 24h price momentum (%) |
| `alert_sent` | Boolean | Whether a Telegram alert was fired |

### `user_watchlist`
Personal watchlists. Unique on `(telegram_user_id, wallet_id)`.

| Column | Type | Description |
|---|---|---|
| `telegram_user_id` | Int | Telegram user ID |
| `wallet_id` | UUID (FK) | Watched wallet |
| `created_at` | DateTime | Subscription timestamp |

### `smart_money_cache`
1-hour cache of the smart-money token list from Birdeye endpoint 13.

### `token_enrichment_cache`
6-hour cache of full token mini-reports (security, market, liquidity data).
Prevents redundant Birdeye calls when the same token trades multiple times within the TTL window.

---

## Real-Time Trade Detection

### Solana RPC WebSocket (Primary)

Zentryx monitors whale wallets in real-time using Solana's native **`accountSubscribe`** RPC method via a public WebSocket endpoint.

**How it works:**
1. Subscribe to each of the top 15 tracked whales' account changes (free)
2. On `accountNotification`, fetch the latest transaction via `getSignaturesForAddress` + `getTransaction` (free)
3. Parse token balance deltas to identify DEX swaps
4. Detect trade side (BUY/SELL) and USD value from SOL balance delta
5. Pass to enrichment pipeline (see [Data Enrichment](#data-enrichment) below)

**Latency:** 2–5 seconds (end-to-end from on-chain to live feed)  
**Cost:** $0 (public endpoint)  
**Availability:** ✅ Stable & unthrottled

**URL:** `wss://api.mainnet-beta.solana.com` (default; configurable via `SOLANA_RPC_WS_URL` env var)

### REST Polling Fallback (Secondary)

If Solana RPC becomes unavailable, the polling worker monitors 6 popular tokens (SOL, USDC, BONK, WIF, JUP, PYTH) every 20 minutes via Birdeye REST endpoint 16. Trades are matched to tracked whales and emitted with a max 20-minute detection lag.

**Cost:** ~0 CU (free-tier endpoint)  
**Activation:** Automatic if Solana RPC fails

---

## Data Enrichment

After a whale trade is detected (via Solana RPC or polling fallback), the enrichment pipeline adds token intelligence using Birdeye REST endpoints.

### Birdeye API Endpoints

Zentryx uses **13 endpoints** from Birdeye, all available on the free tier:

### Wallet Endpoints

| # | Endpoint | Used For |
|---|---|---|
| 1 | `GET /trader/gainers-losers` | Weekly discovery — top 50 one-week performers |
| 2 | `GET /wallet/v2/pnl/summary` | Per-wallet PnL, snapshots, whale detail page |
| 3 | `GET /wallet/v2/pnl/multiple` | Batch PnL fetch (10 wallets per call) during discovery |
| 4 | `GET /wallet/v2/net-worth-details` | Whale detail page — full portfolio breakdown |
| 5 | `GET /wallet/v2/net-worth` | 6-hour snapshots — portfolio net worth value |

### Token Intelligence Endpoints (Enrichment)

| # | Endpoint | Used For |
|---|---|---|
| 9 | `GET /defi/token_security` | Security score and honeypot flag |
| 10 | `GET /defi/v3/price-stats/single` | 24h price momentum and volume stats |
| 11 | `GET /defi/v3/token/holder` | Holder count |
| 12 | `GET /holder/v1/distribution` | Holder distribution analysis |
| 13 | `GET /smart-money/v1/token/list` | Smart money token list (1-hr cache) |
| 14 | `GET /defi/token_overview` | Market cap, liquidity, symbol |
| 15 | `GET /defi/v3/token/trade-data/single` | Buy/sell counts, volume |
| 16 | `GET /defi/v3/token/txs` | Recent txs (polling fallback only) |

> Endpoints 6, 7, 8, and 17 are implemented in `birdeye.py` but not called in production to conserve compute units.

### Future: Birdeye WebSocket

**Planned upgrade:** When budget allows, we will integrate **Birdeye WebSocket endpoints** for:
- Real-time large trade alerts (`SUBSCRIBE_LARGE_TRADE_TXS`)
- Per-wallet transaction streams (`SUBSCRIBE_WALLET_TXS`)
- Automatic fallback for Solana RPC rate limiting

This will provide ultra-low-latency (1–2s) trade detection alongside existing Solana RPC monitoring. No code changes needed — just swap the RPC endpoint in `.env`.

---

## REST API Reference

Base URL: `http://localhost:8000`

### Health Check

```
GET /health
```

```json
{ "status": "ok", "service": "zentryx-api", "version": "0.2.0" }
```

### Wallets

```
GET  /api/wallets                        — Leaderboard (all tracked whales, sorted by PnL)
GET  /api/wallets/{address}              — Single whale — PnL summary, net worth, label
GET  /api/wallets/{address}/history      — Historical snapshots for charting
POST /api/wallets/discover               — Manually trigger wallet discovery
```

**`GET /api/wallets/{address}/history` query params:**

| Param | Default | Range | Description |
|---|---|---|---|
| `days` | `7` | `1–30` | How many days of snapshots to return |

### Tokens

```
GET /api/tokens/{address}/mini-report    — Full token intelligence (security, market, liquidity)
```

### Trades & Live Feed

```
GET       /api/trades    — Recent trade events from DB (feed pre-population on page load)
WebSocket /ws/feed       — Real-time trade broadcast stream
```

**`GET /api/trades` query params:**

| Param | Default | Range | Description |
|---|---|---|---|
| `limit` | `50` | `1–200` | Number of trade events to return |
| `hours` | `24` | `1–720` | How many hours back to fetch |

---

## Telegram Bot

Built with `python-telegram-bot`. All commands read from PostgreSQL or in-memory cache — **zero Birdeye compute units are consumed during any bot interaction**.

### Commands

| Command | Arguments | Description |
|---|---|---|
| `/start` | — | Welcome message; confirms bot is online |
| `/wallets` | — | List all tracked whales with PnL, win rate, and trade count |
| `/stats` | — | Aggregates: total PnL, average win rate, best performer |
| `/top` | `[n]` | Top N whales by PnL (default 5) |
| `/wallet` | `[address]` | Look up a wallet by address (partial match supported) |
| `/filter` | `[win_rate%]` | Show whales above the given win rate threshold |
| `/watch` | `[address]` | Subscribe to a wallet — receive a personal DM on every large trade |
| `/unwatch` | `[address]` | Remove a wallet from your personal watchlist |
| `/my-wallets` | — | View all wallets in your personal watchlist |
| `/help` | — | Full command reference |

### Alerts

**Startup ping** — sent once per backend boot, costs 0 CU:
```
🟢 Zentryx is online. Monitoring live trades on Solana.
```

**Trade alert** — broadcast to `TELEGRAM_CHAT_ID` when a $2,000+ trade is detected:
```
🐋 Whale #1 — BUY
Token: $BONK
Value: $12,450.00
Security: 🟢 Safe (82/100)
Smart Money: ✅ Yes
Momentum (24h): +14.3%
```

**Watchlist DM** — sent privately to users who have `/watch`-ed the trading wallet.

### Rate Limiting

A **5-second per-chat cooldown** prevents spam. `/start` and `/help` are exempt.

---

## Getting Started

### Prerequisites

- **Node.js** 18+ with npm
- **Python** 3.13+
- **PostgreSQL** database (Prisma Cloud, Supabase, Railway, or local)
- **Birdeye API key** — free tier at [birdeye.so](https://birdeye.so)
- **Telegram bot token** — create via [@BotFather](https://t.me/BotFather)

---

### 1. Clone the Repository

```bash
git clone https://github.com/JUICEWRLD998/zentryx.git
cd zentryx
```

### 2. Frontend

```bash
npm install
```

Create `.env.local` in the project root:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

Start the development server:

```bash
npm run dev
# Frontend available at http://localhost:3000
```

### 3. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Create `backend/.env`:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
BIRDEYE_API_KEY=your_birdeye_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

Set up the database schema:

```bash
prisma db push       # apply schema to PostgreSQL
prisma generate      # regenerate Python client
```

Start the server:

```bash
# Windows (from the project root)
$env:PATH = "C:\path\to\zentryx\backend\.venv\Scripts;" + $env:PATH
python -m uvicorn main:app --port 8000 --reload --app-dir backend

# macOS / Linux
cd backend && uvicorn main:app --port 8000 --reload
```

### 4. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"zentryx-api","version":"0.2.0"}
```

Open Telegram and send `/start` to your bot — you should receive a welcome message.

---

## Project Structure

```
zentryx/
|
+-- app/                              # Next.js App Router pages
|   +-- layout.tsx                   # Root layout + ThemeProvider
|   +-- globals.css                  # Tailwind + custom theme tokens
|   +-- page.tsx                     # Landing page (hero, features, CTA)
|   +-- dashboard/page.tsx           # Whale leaderboard with stats
|   +-- live/page.tsx                # Real-time WebSocket trade feed
|   +-- token/[address]/page.tsx     # Token detail (security, market, liquidity)
|   +-- wallet/[address]/page.tsx    # Whale profile (PnL, win rate, history)
|
+-- components/
|   +-- theme-provider.tsx           # next-themes wrapper
|   +-- theme-toggle.tsx             # Dark / light mode button
|   +-- ui/                          # shadcn/ui primitives (button, sheet...)
|
+-- lib/
|   +-- useWebSocket.ts              # WebSocket hook for live feed page
|   +-- utils.ts                     # Shared utility helpers
|
+-- backend/
|   +-- main.py                      # FastAPI app, lifespan, CORS, route registration
|   +-- db.py                        # Shared Prisma client with graceful degradation
|   +-- scheduler.py                 # APScheduler — 3 cron/interval jobs
|   |
|   +-- models/
|   |   +-- schemas.py               # Pydantic v2 schemas (request + response)
|   |
|   +-- routers/
|   |   +-- wallets.py               # /api/wallets and /api/wallets/{address}
|   |   +-- ws.py                    # /ws/feed, /api/trades, /api/tokens/{addr}/mini-report
|   |
|   +-- services/
|   |   +-- birdeye.py               # Async Birdeye client — 17 endpoints with retry
|   |   +-- solana_rpc_ws.py         # Solana RPC WebSocket — real-time accountSubscribe
|   |   +-- polling_worker.py        # REST polling fallback — 6 tokens, 20-min interval
|   |   +-- enrichment.py            # Trade enrichment pipeline + 6-hr token cache
|   |   +-- snapshot.py              # 6-hour wallet snapshot capture + TTL cleanup
|   |   +-- wallet_discovery.py      # Weekly top-15 discovery + batched PnL fetch
|   |   +-- ws_manager.py            # WebSocket connection pool + broadcast
|   |   +-- telegram.py              # Bot commands, trade alerts, watchlist DMs
|   |
|   +-- prisma/
|   |   +-- schema.prisma            # 6-table PostgreSQL schema
|   |
|   +-- .env                         # API keys — not committed to git
|   +-- requirements.txt             # Python dependencies
|   +-- .venv/                       # Virtual environment
|
+-- public/                           # Static assets
+-- components.json                   # shadcn/ui configuration
+-- next.config.ts                    # Next.js configuration
+-- tsconfig.json                     # TypeScript strict config
+-- postcss.config.mjs                # PostCSS + Tailwind
+-- README.md
```

---

## Quota & Cost Optimisation

Zentryx is engineered to maximise real-time trade detection while staying within free-tier compute constraints.

### Real-Time Detection (Solana RPC WebSocket)

No compute units consumed — Solana RPC public endpoints are free and unthrottled. Whale wallets are monitored 24/7 via `accountSubscribe` for instant trade detection.

**Fallback:** If Solana RPC becomes rate-limited, the REST polling worker automatically takes over.

### Token Enrichment Cache (6-hour TTL)

The first trade involving a token triggers 8 Birdeye calls (endpoints 9–15) to build a full `TokenMiniReport`. The result is stored in `token_enrichment_cache` with a 6-hour TTL. Every subsequent trade on that token within the window costs **0 CU**.

### Smart Money Cache (1-hour TTL)

The smart-money token list (endpoint 13) is fetched once per hour and stored in `smart_money_cache`. All enrichment checks read from this cache — a single Birdeye call funds thousands of flag lookups.

### REST Polling Interval (20 minutes)

The polling worker monitors 6 tokens at a 1,200-second interval (reduced from 300s). Polling cost was reduced by **75%** with this change alone.

### Estimated Daily Compute Unit Budget

| Operation | Frequency | CU / day |
|---|---|---|
| Wallet discovery | Weekly (amortised) | ~2 |
| 6-hour snapshots (15 wallets × 2 endpoints) | 4× per day | ~120 |
| REST polling (6 tokens × 20-min interval) | 72 polls / day | ~36 |
| Token enrichment (cache miss only) | Per unique token | ~8 per miss |
| **Real-time trade detection (Solana RPC)** | Continuous | **0** |
| Telegram commands | On demand | **0** |
| **Estimated total** | | **~158–200 CU / day** |

> **Note:** Solana RPC usage is free and unlimited. Compute units are only spent on Birdeye enrichment (token security, honeypot detection) which happens *after* a trade is detected.

### APScheduler Jobs

| Job | Schedule | Action |
|---|---|---|
| `discover_wallets` | Sunday midnight (weekly) | Refresh top-15 whale list from Birdeye |
| `take_wallet_snapshots` | Every 6 hours | Capture PnL + net worth for all tracked wallets |
| `cleanup_old_trades` | Daily at 03:00 UTC | Delete trade events older than 30 days and expired cache rows |

---

## Deployment

### Frontend — Vercel

1. Push to GitHub
2. Import the repository on [vercel.com](https://vercel.com)
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` — your backend URL
   - `NEXT_PUBLIC_WS_URL` — your backend WebSocket URL (`wss://` in production)
4. Deploy — Vercel rebuilds on every push to `main`

### Backend — Render

1. Create a new Web Service on [render.com](https://render.com)
2. Connect your GitHub repository
3. Set the root directory to `backend`
4. Add environment variables:
   - `DATABASE_URL` — PostgreSQL connection string
   - `BIRDEYE_API_KEY` — Birdeye API key (free tier)
   - `TELEGRAM_BOT_TOKEN` — Telegram bot token from @BotFather
   - `TELEGRAM_CHAT_ID` — Your Telegram chat ID
5. Set the start command:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```
6. Deploy — Render redeploys automatically on GitHub pushes to `main`

### Backend — Railway / Fly.io (Alternative)

1. Create a new project and connect the GitHub repository
2. Set the root directory to `/backend`
3. Add environment variables: `DATABASE_URL`, `BIRDEYE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
4. Set start command:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

> Use `wss://` (not `ws://`) for the WebSocket URL in production.

---

## Future Improvements

### 1. **Birdeye WebSocket Upgrade (Paid API Plan)**

**Current:** REST polling every 20 minutes on 6 monitored tokens (free tier fallback)

**Improvement:** Upgrade to Birdeye paid API plan to unlock WebSocket access (`wss://public-api.birdeye.so/socket`). This enables:
- Real-time trade detection instead of 20-minute delays
- Per-wallet transaction subscriptions (all whales, all tokens)
- Sub-second latency for copy trading signals
- Reduced REST polling overhead (immediate data source)

**Impact:** 
- Trading margin increases from 20 min to near-real-time
- Capture whale trades on any token, not just the 6 monitored ones
- Full copy trading accuracy

### 2. **Wallet Discovery Frequency (Weekly → Daily or 2x/Week)**

**Current:** Top-15 whale discovery runs every Sunday (weekly)

**Improvement:** Increase discovery frequency to:
- **2x/week** (Sunday + Wednesday) to catch mid-week momentum shifts
- **Daily** for ultra-responsive leaderboard updates

**Impact:**
- Identify emerging whale performers faster
- Reduce lag when a whale's PnL changes dramatically mid-week
- More accurate tracking of volatile market conditions

### 3. **Automated Copy Trading Execution**

**Current:** Zentryx detects whale trades and alerts users; users manually execute trades

**Improvement:** Implement automated trade mirroring:
- User connects Solana wallet (via phantom.app or similar)
- Set allocation strategy (fixed $X per whale trade, or % of detected trade size)
- Zentryx automatically executes matching swaps on your behalf
- Backtesting mode to simulate trades before going live

**Impact:**
- Eliminate manual execution delay (human reaction time removed)
- Precise position sizing and risk management
- Quantifiable historical returns vs whale performance

---

## License

MIT — free to use, modify, and distribute.

---

*Built on Solana. Track smarter. Trade smarter.*
