# Zentryx Sprint 4 — First Place Push

**Sprint 3 result:** 2nd place — 9.4/10 Technical Depth · 9.4/10 Utility  
**Target:** 10/10 both dimensions — activate every dormant premium endpoint, ship 5 net-new elite features, wire all panels to real Birdeye data, test everything.

---

## Audit: Where Sprint 3 Left Gaps

| Dimension | Sprint 3 Score | Root Cause |
|---|---|---|
| Utility | 9.4 / 10 | Smart money heatmap, AI briefing, rotation detector not built |
| Technical Depth | 9.4 / 10 | 7 premium endpoints wrapped in birdeye.py but NEVER surfaced |

### Premium Endpoints Wrapped but Never Used

These exist in `backend/services/birdeye.py` but have zero API routes or frontend features:

| # | Endpoint | Wrapper | Missing Feature |
|---|---|---|---|
| 4 | `/wallet/v2/net-worth-details` | `get_wallet_net_worth_details` | Wallet breakdown panel |
| 6 | `/wallet/v2/balance-change` | `get_wallet_balance_change` | Balance delta timeline |
| 7 | `/v1/wallet/tx_list` | `get_wallet_tx_list` | Activity feed on wallet page |
| 8 | `/defi/v2/tokens/top_traders` | `get_top_traders` | Top traders tab on token page |
| 10 | `/defi/v3/price-stats/single` | `get_price_stats` | Multi-timeframe stats panel |
| 11+12 | `/defi/v3/token/holder` + `/holder/v1/distribution` | `get_token_holders` + `get_holder_distribution` | Holder distribution chart |
| 15 | `/defi/v3/token/trade-data/single` | `get_token_trade_data` | Buy/sell flow panel |
| 17 | `/defi/v3/token/exit-liquidity` | `get_exit_liquidity` | Exit liquidity estimator |

### Features Computed but Never Shown

- `signal_stats.py` runs every 2h computing signal profitability → **cached result never exposed by any API route**
- `send_daily_briefing()` scheduled in `scheduler.py` → **no `/api/briefing` route, no dashboard card**
- Whale consensus tracked in-memory → **no rotation detection built**

### Features Planned in Sprint 3 but Not Built

- Smart Money Inflow/Outflow Heatmap (`/smart-money/v1/token/inflow-outflow` — endpoint not even wrapped)
- Token Overlap Matrix (which tokens do tracked whales share?)
- Whale Rotation Detector (SELL token A → BUY token B within 4h)
- Demo Mode (no seeded deterministic fallback data)
- Pipeline Stats overlay on live feed
- CSV export from leaderboard

---

## Feature List — Sprint 4

### Phase 1 — Activate 7 Dormant Premium Endpoints

All 8 new backend routes get matching frontend UI panels. This alone converts 7 premium API wrappers from dead code into live intelligence.

#### 1a. Backend: 5 New Token Routes (tokens.py)

| Route | Birdeye Endpoint | Feature |
|---|---|---|
| `GET /api/tokens/{address}/top-traders` | `/defi/v2/tokens/top_traders` (endpoint 8) | Top 10 traders for this token — each links to wallet profile |
| `GET /api/tokens/{address}/holders` | `/defi/v3/token/holder` + `/holder/v1/distribution` (11+12) | Holder count + distribution breakdown |
| `GET /api/tokens/{address}/trade-data` | `/defi/v3/token/trade-data/single` (endpoint 15) | Buy/sell count + volume flow |
| `GET /api/tokens/{address}/exit-liquidity` | `/defi/v3/token/exit-liquidity` (endpoint 17) | Slippage estimate for $1K / $5K / $10K exits |
| `GET /api/tokens/{address}/price-stats` | `/defi/v3/price-stats/single` (endpoint 10) | 1H / 4H / 24H price stats side-by-side |

#### 1b. Backend: 3 New Wallet Routes (wallets.py)

| Route | Birdeye Endpoint | Feature |
|---|---|---|
| `GET /api/wallets/{address}/balance-change` | `/wallet/v2/balance-change` (endpoint 6) | 24H and 7D balance delta |
| `GET /api/wallets/{address}/net-worth-details` | `/wallet/v2/net-worth-details` (endpoint 4) | Full asset class breakdown |
| `GET /api/wallets/{address}/activity` | `/v1/wallet/tx_list` (endpoint 7) | Last 20 transactions — type, amount, time |

#### 1c. Frontend: Token Detail Page — 5 New Tabs

New tabbed section on `/token/[address]`:
1. **Top Traders** — ranked table of top wallets trading this token, each links to their Zentryx profile
2. **Holder Distribution** — breakdown bars: top 10 holders %, retail %, unknown % with concentration risk label
3. **Trade Flow** — buy vs sell count + buy vs sell volume bars (live data from Birdeye endpoint 15)
4. **Exit Liquidity** — slippage table for 3 exit sizes ($1K / $5K / $10K) — shows market depth reality
5. **Multi-timeframe Stats** — 1H / 4H / 24H price change + volume side-by-side

#### 1d. Frontend: Wallet Page — 3 New Panels

New panels on `/wallet/[address]`:
1. **Balance Change** — 24H and 7D net worth delta with directional color
2. **Net Worth Breakdown** — asset class split (tokens, SOL, stablecoins) not just a single total
3. **Activity Timeline** — chronological last 20 transactions with type, amount, token label

---

### Phase 2 — Smart Money Inflow/Outflow Heatmap (New Page)

*First time this Birdeye premium endpoint is used anywhere in the codebase.*

- Wrap `/smart-money/v1/token/inflow-outflow` in `birdeye.py`
- New `GET /api/smart-money/heatmap` route — top 20 tokens × 3 time buckets (1H, 4H, 24H)
- New page `app/smart-money/page.tsx` — color grid:
  - Green = net smart money accumulating
  - Red = net smart money distributing
  - Intensity = magnitude of flow
  - Click any cell → token detail page
- Add nav item to navbar

---

### Phase 3 — Token Overlap Matrix on Dashboard

*No new API calls needed — uses existing portfolio endpoint for each tracked whale.*

- New `GET /api/wallets/overlap` route — fetches current portfolio for each tracked whale, finds shared tokens, returns `{ token_address, symbol, whale_count, whales[] }`
- New "Whale Conviction Zones" section on `/dashboard`:
  - Ranked by how many whales hold the token
  - Shows each whale's label who holds it
  - "3 whales hold $WIF" badge → click → token detail
  - EXTREME CONVICTION badge when 4+ whales share a position

---

### Phase 4 — Signal Profitability Surfaced on Frontend

*Computation already runs every 2h via `signal_stats.py`. Zero new API calls needed.*

- New `GET /api/signals/stats` route — returns `get_cached_stats()` directly
- Dashboard: "Signal Performance" stat card showing:
  - `X% of Copy Score 80+ trades were profitable in 24h`
  - Top 3 performing signal tokens with return %
- Live feed: "Outcome" badge on trade cards after 12h (`+47% in 14h` or `-12% in 14h`)

---

### Phase 5 — Whale Rotation Detector

*Net-new algorithmic feature. Detects when a whale exits one token and enters another.*

- New `services/rotation_detector.py`:
  - Queries `trade_event_table` for SELL on token A followed by BUY on token B by same wallet within 4h
  - Returns list of `{ wallet_label, from_token, to_token, from_usd, to_usd, detected_at }`
- New `GET /api/rotations` route — last 10 rotation events
- Live feed gets `ROTATION` badge alongside `CONSENSUS`
- Dashboard: "Recent Whale Rotations" card:
  - `Whale X rotated $WIF → $BONK 3h ago ($45K)`
  - Links both tokens to their detail pages
- Telegram: `ROTATION DETECTED` alert type when a rotation is found during enrichment

---

### Phase 6 — AI Daily Market Briefing on Dashboard

*`send_daily_briefing()` already scheduled at 9AM UTC. Just needs a backend cache + route + UI.*

- New `services/daily_briefing.py`:
  - Reads DB: top 3 tokens with repeated smart money BUY in last 24h
  - Generates Gemini 3-bullet briefing: "Watch", "Accumulating", "Rotation detected"
  - Stores result in module-level cache with timestamp
- New `GET /api/briefing` route — returns cached daily briefing
- Dashboard: pinned "Today's Market Briefing" card:
  - Three bullet points with token links
  - "Generated by Gemini · Updated 09:00 UTC" footer
  - Refreshes every 6h in case of manual re-run

---

### Phase 7 — Demo Mode + Pipeline Stats + CSV Export

*Polish for demo day — ensures no blank screen moments.*

- **Demo Mode**: `DEMO_MODE=true` env var → backend stubs all Birdeye calls with seeded deterministic data
  - Fake 15 tracked wallets with realistic PnL numbers
  - Fake trade events with copy scores, consensus flags
  - Frontend reads `?demo=true` to show demo banner
- **Pipeline Stats**: New `GET /api/stats/pipeline` route → `{ api_calls_today, tokens_scanned, trades_enriched, last_refresh_at, ws_status }`
  - Small overlay component on live feed page (bottom-left corner)
  - Counts incremented on every Birdeye call, trade enrichment, polling cycle
- **CSV Export**: Download button on `/dashboard` leaderboard
  - Exports: rank, address, label, PnL, win rate, trade count
  - One-click → downloads `zentryx-whales.csv`

---

## Files to Create / Modify

### New Files
| File | Purpose |
|---|---|
| `backend/services/rotation_detector.py` | Whale rotation detection algorithm |
| `backend/services/daily_briefing.py` | AI daily briefing generator + cache |
| `backend/routers/smart_money.py` | Heatmap + overlap + signals + briefing + pipeline routes |
| `app/smart-money/page.tsx` | Smart money inflow/outflow heatmap page |

### Modified Files
| File | Changes |
|---|---|
| `backend/services/birdeye.py` | Add `get_smart_money_inflow_outflow()` wrapper |
| `backend/routers/tokens.py` | Add 5 new GET routes (top-traders, holders, trade-data, exit-liquidity, price-stats) |
| `backend/routers/wallets.py` | Add 3 new GET routes (balance-change, net-worth-details, activity) |
| `backend/main.py` | Include new smart_money router + pipeline stats counter |
| `backend/scheduler.py` | Register daily briefing job (already done — verify wiring to new service) |
| `app/token/[address]/page.tsx` | Add 5 new tabbed panels |
| `app/wallet/[address]/page.tsx` | Add 3 new panels |
| `app/dashboard/page.tsx` | Signal Performance card + Whale Conviction Zones + Rotations |
| `app/live/page.tsx` | Outcome badges on old trades + Pipeline Stats overlay |
| `components/navbar.tsx` | Add Smart Money nav link |

---

## Build Schedule

| Phase | What Gets Built | Test File | Impact |
|---|---|---|---|
| **Phase 1** | 8 backend routes (done) + 8 frontend panels on token/wallet pages | `test_sprint4_phase1.py` | Converts 8 dormant premium endpoints into live features |
| **Phase 2** | Smart money heatmap (new Birdeye endpoint + new page) | `test_sprint4_phase2.py` | Brand-new visual, most impressive in a live demo |
| **Phase 3** | Token Overlap Matrix on dashboard | `test_sprint4_phase3.py` | Algorithmic, zero extra API calls, high insight value |
| **Phase 4** | Signal profitability on frontend (route + dashboard + live feed) | `test_sprint4_phase4.py` | Already computed — just wire the UI |
| **Phase 5** | Whale Rotation Detector (service + route + badges + Telegram) | `test_sprint4_phase5.py` | Net-new real-time intelligence |
| **Phase 6** | AI Daily Briefing (service + route + dashboard card) | `test_sprint4_phase6.py` | AI integration depth signal for judges |
| **Phase 7** | Token detail — 5 new intelligence tabs (frontend) | Manual / Playwright | Every premium endpoint visible to visitors |
| **Phase 8** | Wallet detail — 3 new panels (frontend) | Manual / Playwright | Complete wallet intelligence surface |
| **Phase 9** | Demo Mode + Pipeline Stats + CSV Export | `test_sprint4_phase9.py` | Demo-day safety + technical depth polish |

---

## Test Scripts

| File | Tests |
|---|---|
| `backend/test_sprint4_phase1.py` | Route shapes, required fields, HTTP 200 on known tokens/wallets |
| `backend/test_sprint4_phase2.py` | Birdeye inflow/outflow wrapper + heatmap route output format |
| `backend/test_sprint4_phase3.py` | Overlap algorithm: shared tokens detected, no-overlap case, response schema |
| `backend/test_sprint4_phase4.py` | Signal stats cache population + route response |
| `backend/test_sprint4_phase5.py` | Rotation detector: detects SELL→BUY within 4h, rejects outside window, empty case |
| `backend/test_sprint4_phase6.py` | Briefing cache set/get, scheduler job registered, route returns correct fields |
| `backend/test_sprint4_phase9.py` | Pipeline counter increment, stats route schema |

---

## Verification Checklist

### Phase 1 (Backend)
- [ ] `GET /api/tokens/{address}/top-traders` → list with `address`, `pnl_usd`, `trade_count`, `is_tracked`
- [ ] `GET /api/tokens/{address}/holders` → `total_holders`, `top10_pct`, `concentration_risk`
- [ ] `GET /api/tokens/{address}/trade-data` → `buy_count`, `sell_count`, `buy_ratio`, `pressure`
- [ ] `GET /api/tokens/{address}/exit-liquidity` → `slippage_estimates` array, `rating`
- [ ] `GET /api/tokens/{address}/price-stats` → `1h`, `4h`, `24h` keys with `price_change_pct`
- [ ] `GET /api/wallets/{address}/balance-change` → `change_24h_usd`, `change_7d_usd`
- [ ] `GET /api/wallets/{address}/net-worth-details` → `total_usd`, `categories`, `breakdown`
- [ ] `GET /api/wallets/{address}/activity` → list with `signature`, `type`, `value_usd`, `timestamp`

### Phase 2 (Smart Money Heatmap)
- [ ] `GET /api/smart-money/heatmap` → array of `{ token, 1h, 4h, 24h }` flow objects
- [ ] `/smart-money` page renders a colored grid (non-empty)

### Phase 3 (Overlap Matrix)
- [ ] `GET /api/wallets/overlap` → `{ token_address, symbol, whale_count, whales[] }`
- [ ] Dashboard shows "Whale Conviction Zones" section

### Phase 4 (Signal Profitability)
- [ ] `GET /api/stats/profitability` → `{ win_rate, avg_return_pct, top_performers[] }`
- [ ] Dashboard stat card shows win rate %
- [ ] Live feed shows Outcome badge on trades > 12h old

### Phase 5 (Rotation Detector)
- [ ] `GET /api/rotations` → list with `from_token`, `to_token`, `wallet_label`, `detected_at`
- [ ] ROTATION badge visible on live feed for detected rotations
- [ ] Dashboard shows "Recent Whale Rotations" card

### Phase 6 (AI Briefing)
- [ ] `GET /api/briefing` → `{ bullets[], generated_at, tokens_analyzed }`
- [ ] Dashboard shows pinned briefing card with timestamp

### Phase 7–8 (Frontend Panels)
- [ ] Token page shows 5-tab intelligence panel below the chart
- [ ] Wallet page shows Balance Change, Net Worth Breakdown, Activity Timeline tabs

### Phase 9 (Polish)
- [ ] `GET /api/stats/pipeline` → `{ api_calls_today, tokens_scanned, trades_enriched }`
- [ ] Pipeline overlay visible on live feed page
- [ ] CSV export button on dashboard downloads a valid CSV file
- [ ] Demo mode (`?demo=true`) loads with seeded data, shows banner
