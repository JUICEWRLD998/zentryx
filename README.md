# Zentryx

Real-time Solana intelligence platform for whale tracking, token analysis, signal quality, discovery scanning, and Telegram-native execution workflows.

Zentryx started as a copy-trading terminal and now operates as a broader intelligence stack:
- Whale discovery and ranking
- Live event ingestion and enrichment
- Token-level AI analysis
- Discovery surfaces (trending, movers, new listings, overlap, heatmap)
- Paper trading and automated alert monitoring
- Telegram command center for day-to-day operations

## What Zentryx Does

### 1) Wallet Intelligence
- Seeds candidate wallets from Birdeye weekly gainers/losers (1W, PnL-ranked sample)
- Applies qualification filters: positive PnL, minimum win rate, and minimum trade count
- Maintains ranked tracked-wallet leaderboard by qualified PnL
- Persists wallets and periodic snapshots for historical views

### 2) Real-Time Trade Intelligence
- Subscribes to Solana account activity via RPC WebSocket
- Parses, filters, and enriches significant trade events
- Stores events and broadcasts live feed updates
- Sends Telegram alerts with enriched context

### 3) Token Intelligence and AI
- Aggregates token overview, security, liquidity, and flow data
- Calculates score dimensions used by frontend token pages
- Generates Groq-based token insight paragraphs
- Falls back gracefully when AI is unavailable

### 4) Discovery and Market Surfaces
- Trending tokens with smart-money cross-reference metadata
- New listings with risk flags and age metrics
- Top movers (gainers and losers)
- Smart money heatmap over recent buckets
- Token overlap (held/traded by multiple tracked wallets)

### 5) Trader Workflow Tools
- Paper trade lifecycle (open, list, manual close)
- Price alerts (create, list, cancel)
- Background monitor for TP/SL and target triggers
- Telegram command support for watchlists, signals, analysis, and discovery

## Architecture

### Frontend
- Next.js App Router (TypeScript)
- Tailwind CSS v4 + component primitives
- Live pages for dashboard, wallet profiles, token details, movers, trending, and new listings

### Backend
- FastAPI (async)
- SQLAlchemy Async + asyncpg
- APScheduler for recurring jobs
- Solana RPC WebSocket listener for low-latency detection
- Birdeye client layer with retries and endpoint wrappers
- Groq integration for AI narrative analysis
- Telegram bot command loop + outbound alerting

### Data Layer
- PostgreSQL tables created automatically at startup if missing
- Core entities include wallets, snapshots, trade events, watchlists, cache tables, paper trades, price alerts, and signal outcomes

## Product Surfaces

### Web Routes
- /
- /dashboard
- /live
- /wallet/[address]
- /token/[address]
- /movers
- /trending
- /new-listings

### Core Backend Routes

Health:
- GET /health

Wallets:
- GET /api/wallets
- GET /api/wallets/{address}
- GET /api/wallets/{address}/history
- GET /api/wallets/{address}/portfolio
- POST /api/wallets/discover

Tokens and Discovery:
- GET /api/tokens/{address}/mini-report
- GET /api/tokens/{address}/ohlcv
- GET /api/tokens/{address}/overview
- GET /api/tokens/{address}/insight
- GET /api/tokens/{address}/whale-buys
- GET /api/movers
- GET /api/trending
- GET /api/new-listings
- GET /api/heatmap
- GET /api/tokens/overlap
- GET /api/stats/profitability

Trades and Alerts:
- GET /api/trades
- POST /api/trades
- PATCH /api/trades/{trade_id}/close
- POST /api/alerts
- GET /api/alerts
- DELETE /api/alerts/{alert_id}

Live Stream:
- WS /ws/feed

## Wallet Ranking Methodology

Current tracked-wallet ranking is intentionally conservative and compute-budget aware.

Data source:
- Candidate wallets come from Birdeye gainers/losers using 1W timeframe and PnL sort.
- Birdeye currently caps this response to a small candidate set per call.

Qualification filters:
- Positive total PnL
- Minimum win-rate threshold
- Minimum trade-count threshold
- Must have current non-dust holdings 

Ranking and persistence:
- Qualified wallets are ranked by total PnL descending.
- Leaderboard labels are assigned as Whale #1, Whale #2, etc.
- Results are kept in memory for low-latency reads and upserted to PostgreSQL.

What this means in practice:
- Zentryx tracks a high-signal sampled cohort of top-performing wallets, not an exhaustive global ranking of all Solana wallets.
- Wallets that are historically strong but currently hold no active positions can be filtered out of the tracked set.
- This is a deliberate hackathon tradeoff for reliability, speed, and API efficiency.
- 
## Telegram Bot Commands

Supported command set:
- /start
- /help
- /wallets
- /stats
- /top
- /wallet
- /filter
- /watch
- /unwatch
- /my-wallets
- /track
- /my-trades
- /alert
- /my-alerts
- /cancel-alert
- /test_alert
- /signal
- /analyze
- /close-trade
- /trending
- /new-listing

The bot also registers a command menu through Telegram API for improved discoverability.

## Birdeye Integrations

The Birdeye client includes wallet, token, discovery, and smart-money endpoints used by routing, enrichment, and monitoring services.

Key endpoints in active workflows include:
- /trader/gainers-losers
- /wallet/v2/pnl/summary
- /wallet/v2/net-worth
- /v1/wallet/token_list
- /defi/token_overview
- /defi/token_security
- /defi/price
- /defi/ohlcv
- /defi/v3/price-stats/single
- /defi/v3/token/holder
- /holder/v1/distribution
- /defi/v3/token/trade-data/single
- /defi/v3/token/txs
- /defi/tokenlist
- /defi/token_trending
- /defi/v2/tokens/new_listing
- /smart-money/v1/token/list

Implemented but currently not used in production discovery path:
- /wallet/v2/pnl/multiple (disabled in discovery due unstable response contract in live usage)

## Getting Started

## Prerequisites
- Node.js 18+
- Python 3.11+
- PostgreSQL-compatible DATABASE_URL
- Birdeye API key
- Telegram bot token
- Groq API key (for AI features)

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
