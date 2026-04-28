# Zentryx — Solana Whale Copy-Trading Intelligence Terminal

Real-time on-chain whale tracking and copy-trading signals on Solana. Track top-performing wallets, get instant alerts when they move, and make smarter trades with confidence.

**Live Demo**: [zentryx.vercel.app](https://zentryx.vercel.app) (when deployed)

---

## 🎯 Features

- **Live Trade Feed**: Watch whale transactions hit the blockchain in real-time via WebSocket with REST polling fallback
- **Whale Leaderboard**: Track top-performing wallets by PnL, win rate, and trade count (7-day window)
- **Token Intelligence**: Deep-dive into tokens with security scoring, honeypot detection, and smart money signals
- **Telegram Bot Commands**:
  - `/start` — Welcome message
  - `/wallets` — List all tracked whales
  - `/stats` — Aggregate metrics across all wallets
  - `/top [n]` — Top N whales by PnL
  - `/wallet [address]` — Look up specific wallet details
  - `/filter [%]` — Filter whales by minimum win rate
  - `/help` — Command reference
- **Instant Alerts**: Telegram notifications when tracked whales make $5,000+ trades
- **Dark/Light Mode**: Toggle between dark (terminal) and light themes
- **Responsive Design**: Mobile-first, works on all devices

---

## 🛠️ Tech Stack

### Frontend
- **Next.js 16.2.4** (App Router, TypeScript)
- **Tailwind CSS v4** with custom Zentryx theme
- **Framer Motion** for animations
- **Recharts** for analytics (radial charts, pie charts)
- **Lucide React** for icons
- **next-themes** for dark/light mode
- **shadcn/ui** components

### Backend
- **FastAPI** (Python 3.14) with async/await
- **APScheduler** for weekly wallet discovery cron jobs
- **python-telegram-bot** for bot commands and alerts
- **httpx** for Birdeye REST API calls with rate-limit retry logic
- **Pydantic v2** for data validation
- **Uvicorn** ASGI server

### External APIs
- **Birdeye API** (free tier) — Solana on-chain data, trader leaderboards, token metrics, PnL summaries
- **Telegram Bot API** — Command handling and real-time alerts

---

## 🚀 Quick Start

### Prerequisites
- Node.js 18+ and npm
- Python 3.13+
- Telegram Bot Token (from BotFather)
- Birdeye API Key (free tier)

### 1. Frontend Setup

```bash
cd zentryx
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`

**Environment variables** (`.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

### 2. Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

**Environment variables** (`.env`):
```
BIRDEYE_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

**Start server**:
```bash
cd backend
& ".venv\Scripts\uvicorn.exe" main:app --port 8000 --reload  # Windows
uvicorn main:app --port 8000 --reload  # macOS/Linux
```

Backend API runs at `http://localhost:8000`

### 3. Test Bot Commands

Open your Telegram chat and type:
- `/start` — bot responds with welcome message
- `/wallets` — lists tracked whales (if available)
- `/help` — shows all commands

---

## 📁 Project Structure

```
zentryx/
├── app/                          # Next.js frontend
│   ├── page.tsx                 # Landing page (hero + features)
│   ├── dashboard/page.tsx       # Whale leaderboard
│   ├── live/page.tsx            # Real-time trade feed
│   ├── token/[address]/page.tsx # Token detail page
│   ├── wallet/[address]/page.tsx # Whale detail page
│   ├── layout.tsx               # Root layout + theme provider
│   └── globals.css              # Tailwind + theme variables
├── components/
│   ├── theme-toggle.tsx         # Dark/light mode button
│   ├── theme-provider.tsx       # next-themes wrapper
│   └── ui/                      # shadcn components
├── backend/                      # FastAPI server
│   ├── main.py                  # Entry point, lifespan, routes
│   ├── models/
│   │   └── schemas.py           # Pydantic schemas
│   ├── routers/                 # Endpoint handlers
│   │   ├── wallets.py           # GET /api/wallets, /api/wallets/{address}
│   │   ├── tokens.py            # GET /api/tokens/{address}/mini-report
│   │   └── ws.py                # WebSocket stream
│   ├── services/
│   │   ├── birdeye.py           # Birdeye API client (17 endpoints)
│   │   ├── wallet_discovery.py  # Weekly top-wallet discovery + filtering
│   │   ├── telegram.py          # Bot commands + alerts + cooldown
│   │   ├── polling_worker.py    # REST fallback for 6 tokens (90s interval)
│   │   └── birdeye_ws.py        # WebSocket listener + trade enrichment
│   ├── .env                     # API keys (not in git)
│   ├── requirements.txt         # Python dependencies
│   └── .venv/                   # Virtual environment
├── public/                       # Static assets
├── package.json
├── tsconfig.json
├── next.config.ts
└── README.md
```

---

## 🎮 Usage Guide

### Landing Page (`/`)
- Hero section with elevator pitch
- Live stats: whales tracked, total PnL, best win rate
- "How It Works" explainer (3 steps)
- Feature highlights
- CTA buttons to dashboard and Telegram bot

### Dashboard (`/dashboard`)
- Hero stats (3 cards): whales tracked, total PnL, best win rate
- Sortable whale leaderboard: rank, address, 7-day PnL, win rate, trade count
- Click "VIEW →" to see whale detail page

### Live Feed (`/live`)
- Real-time trade stream (WebSocket)
- Trade cards with token symbol, wallet, side (BUY/SELL), USD value
- Click trade card to open slide-over with:
  - Trade details (token address, security score, momentum)
  - Links to Solscan, Jupiter, and token detail page
  - Option to view whale profile

### Token Detail (`/token/[address]`)
- Hero: token symbol, current price, 24h momentum, market cap
- Security score (radial chart), honeypot status, smart money flags
- Market metrics: price, volume, market cap
- Liquidity & holders: total liquidity USD, holder count, buy/sell ratio pie chart
- Risk overview: security breakdown, token age, contract verified
- External links: Solscan, Jupiter, copy address

### Whale Detail (`/wallet/[address]`)
- Wallet label and address
- 7-day PnL, win rate, trade count metrics
- Recent trades with token details
- Security scoring for each trade

### Telegram Bot

1. **Start bot**: `/start`
   - Confirmation that bot is live

2. **View all wallets**: `/wallets`
   - Lists rank, PnL, win rate, trade count for each tracked whale

3. **Dashboard stats**: `/stats`
   - Total PnL across all wallets
   - Average win rate
   - Best performer (by PnL)
   - Highest win rate

4. **Top N whales**: `/top [n]`
   - Example: `/top 10` shows top 10 whales by PnL
   - Default is 5 if no number given

5. **Lookup wallet**: `/wallet [address]`
   - Example: `/wallet Hm9qLg` (partial match)
   - Shows PnL, win rate, trades, Solscan link

6. **Filter by win rate**: `/filter [n%]`
   - Example: `/filter 70` shows whales with ≥70% win rate
   - Sorted by PnL descending

7. **Get help**: `/help`
   - Lists all commands

**Note**: Commands have a 5-second cooldown per chat (except `/start` and `/help`).

---

## 🔧 How It Works

### Wallet Discovery (Weekly)
1. Query Birdeye `/trader/gainers-losers` endpoint for top 50 1W performers
2. Fetch PnL summary for each wallet (free-tier endpoint)
3. Filter: win rate ≥40%, PnL > $0, trades ≥5
4. Sort by PnL descending, keep top 15
5. Store in-memory + cache for API queries

### Live Trade Pipeline
1. **WebSocket listener** connects to Birdeye real-time stream (paid tier required)
   - If WebSocket unavailable: falls back to REST polling
2. For each $5,000+ trade, enrich with:
   - Token mini-report (security score, honeypot status, momentum, market cap, liquidity)
   - Wallet label (if tracked)
3. Emit to frontend via WebSocket
4. Frontend receives real-time trades in live feed

### REST Polling Fallback
- Polls 6 major tokens (SOL, USDC, BONK, WIF, JUP, PYTH) every 90 seconds
- Fetches recent txs, filters by $5,000+ USD value
- Enriches with token data
- Emits to frontend

### Bot Command Flow
1. User types `/wallets` in Telegram
2. Bot checks cooldown (5s per chat)
3. If cooldown active: "slow down" message
4. Else: fetch tracked wallets from in-memory cache, format HTML, send to chat
5. Cooldown resets for that chat

### Telegram Alerts
1. Trade detected via WebSocket or REST polling
2. Format alert: whale label, token symbol, side, USD value, security score, smart money flag, momentum
3. Send to configured Telegram chat (from `TELEGRAM_CHAT_ID` env var)
4. Example: "🚀 Whale #1 BUY $SOL | Value: $12,345 | Security: 🟢 Safe (78/100) | Smart Money: ✅ Yes"

---

## 📊 Data Architecture

### In-Memory Store
- **Tracked Wallets**: Refreshed weekly (APScheduler cron), cached during runtime
- **Command Cooldown Map**: {chat_id: timestamp}, flushed on restart
- **WebSocket Clients**: Connection pool for broadcasting trades

### Endpoints

**Wallets**:
- `GET /api/wallets` — List all tracked whales
- `GET /api/wallets/{address}` — Single whale detail (PnL, net worth, trades)

**Tokens**:
- `GET /api/tokens/{address}/mini-report` — Token security, market, liquidity

**WebSocket**:
- `WS /ws/trades` — Real-time trade stream (frontend subscribes)

---

## ⚙️ Configuration

### Environment Variables

**Frontend** (`.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

**Backend** (`.env`):
```
BIRDEYE_API_KEY=your_key_from_birdeye
TELEGRAM_BOT_TOKEN=your_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

### Birdeye API Constraints
- **Free Tier**: 1 request/second per endpoint, daily compute unit limit (resets at UTC midnight)
- **Paid Tier**: WebSocket access, higher rate limits
- Current setup uses **free tier only** — WebSocket disabled, REST fallback enabled

---

## 📱 Deployment

### Frontend → Vercel
```bash
git push origin main
# Import repo on vercel.com
# Set env vars: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WS_URL
# Deploy
```

### Backend → Railway
```bash
# Create Railway project, connect GitHub repo
# Set root to /backend
# Set env vars: BIRDEYE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## 🎨 Theme

- **Default**: Dark mode (terminal aesthetic with neon accents)
- **Light Mode**: Clean off-white palette (toggle via Sun/Moon icon)
- **Colors**:
  - Buy: `#00FFA3` (dark) / `#00A86B` (light)
  - Sell: `#FF4D4D` (dark) / `#DC2626` (light)
  - Cyan: `#00D4FF` (dark) / `#0891B2` (light)

---

## 🛡️ Limitations & Known Issues

1. **Birdeye Free Tier**: No WebSocket; REST polling every 90s as fallback
2. **Hydration Mismatch**: Fixed with `suppressHydrationWarning` on `<html>` tag
3. **Wallet Discovery Delay**: Runs weekly (Sunday midnight) + on startup; ~10-30s to complete
4. **Compute Unit Cap**: Free tier has daily limit; resets at UTC midnight

---

## 📝 License

MIT — Free to use and modify.

---

## 🙋 Support

- **Issues**: Open a GitHub issue
- **Bot Troubleshooting**: Check backend logs (`uvicorn` output)
- **API Errors**: See `backend/services/birdeye.py` for retry logic

---

## 👨‍💻 Development

### Code Style
- TypeScript (strict mode) + ESLint
- Python 3.14 with type hints
- Async/await throughout

### Testing
```bash
npm run build      # Frontend build check
python -m pytest   # Backend tests (if added)
```

### Git Workflow
```bash
git add .
git commit -m "feat: description of change"
git push origin main
```

---

**Built with ❤️ on Solana. Track smarter. Trade smarter.**

