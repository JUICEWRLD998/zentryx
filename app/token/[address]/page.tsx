"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type MiniReport = {
  token_address: string;
  security_score: number | null;
  is_honeypot: boolean | null;
  smart_money_flag: boolean;
  momentum_24h: number | null;
  holder_count: number | null;
  buy_sell_ratio: number | null;
  total_liquidity_usd: number | null;
  symbol: string | null;
  price: number | null;
  market_cap: number | null;
  volume_24h: number | null;
};

type OhlcvCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type WhaleBuy = {
  time: number;
  usd_value: number;
  wallet_label: string;
  smart_money: boolean;
};

type Timeframe = "1D" | "7D" | "30D";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(4)}`;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function secColor(score: number | null): string {
  if (score == null) return "#6b7280";
  if (score >= 70) return "#22c55e";
  if (score >= 40) return "#eab308";
  return "#ef4444";
}

function secLabel(score: number | null): string {
  if (score == null) return "UNKNOWN";
  if (score >= 70) return "SAFE";
  if (score >= 40) return "MODERATE";
  return "RISKY";
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SecurityRadial({ score }: { score: number | null }) {
  const value = score ?? 0;
  const color = secColor(score);
  const data = [{ value, fill: color }];

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative w-32 h-20">
        <ResponsiveContainer width={128} height={80}>
          <RadialBarChart
            cx="50%"
            cy="100%"
            innerRadius="70%"
            outerRadius="100%"
            startAngle={180}
            endAngle={0}
            data={data}
          >
            <RadialBar dataKey="value" cornerRadius={4} background={{ fill: "#1f2937" }} />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-end pb-1">
          <span className="font-mono text-lg font-bold" style={{ color }}>
            {score != null ? score.toFixed(0) : "?"}
          </span>
          <span className="font-mono text-xs text-muted-foreground">/ 100</span>
        </div>
      </div>
      <span className="font-mono text-xs font-semibold tracking-widest" style={{ color }}>
        {secLabel(score)}
      </span>
    </div>
  );
}

function BuySellPie({ ratio }: { ratio: number | null }) {
  if (ratio == null) return <span className="font-mono text-xs text-muted-foreground">—</span>;
  const buyPct = ratio * 100;
  const sellPct = 100 - buyPct;
  const data = [
    { name: "BUY", value: buyPct },
    { name: "SELL", value: sellPct },
  ];
  return (
    <div className="flex items-center gap-3">
      <div className="w-12 h-12">
        <ResponsiveContainer width={48} height={48}>
          <PieChart>
            <Pie data={data} dataKey="value" cx="50%" cy="50%" innerRadius="50%" outerRadius="80%" strokeWidth={0}>
              <Cell fill="#22c55e" />
              <Cell fill="#ef4444" />
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="font-mono text-xs flex flex-col gap-0.5">
        <span className="text-buy">BUY {buyPct.toFixed(0)}%</span>
        <span className="text-sell">SELL {sellPct.toFixed(0)}%</span>
      </div>
    </div>
  );
}

function StatRow({ label, value, valueClass = "text-foreground" }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="font-mono text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono text-xs font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}

function GridCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="font-mono text-xs text-muted-foreground tracking-widest mb-4">{title}</p>
      {children}
    </div>
  );
}

// ── OHLCV Chart ────────────────────────────────────────────────────────────

function fmtTime(unix: number, timeframe: Timeframe): string {
  const d = new Date(unix * 1000);
  if (timeframe === "1D") {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function fmtPrice(n: number): string {
  if (n >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (n >= 1)    return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toPrecision(4)}`;
}

type ChartTooltipProps = {
  active?: boolean;
  payload?: Array<{ value: number; payload: OhlcvCandle }>;
  label?: number;
  timeframe: Timeframe;
};

function ChartTooltip({ active, payload, label, timeframe }: ChartTooltipProps) {
  if (!active || !payload?.length || label == null) return null;
  const candle = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-card shadow-xl px-3 py-2 font-mono text-xs">
      <p className="text-muted-foreground mb-1">{fmtTime(label, timeframe)}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <span className="text-muted-foreground">O</span><span className="text-foreground">{fmtPrice(candle.open)}</span>
        <span className="text-muted-foreground">H</span><span className="text-buy">{fmtPrice(candle.high)}</span>
        <span className="text-muted-foreground">L</span><span className="text-sell">{fmtPrice(candle.low)}</span>
        <span className="text-muted-foreground">C</span><span className="text-foreground font-bold">{fmtPrice(candle.close)}</span>
      </div>
    </div>
  );
}

function OhlcvChart({
  candles,
  whaleBuys,
  timeframe,
}: {
  candles: OhlcvCandle[];
  whaleBuys: WhaleBuy[];
  timeframe: Timeframe;
}) {
  if (!candles.length) {
    return (
      <div className="flex items-center justify-center h-48 font-mono text-xs text-muted-foreground">
        No price data available
      </div>
    );
  }

  // Compute domain with 3% padding
  const closes = candles.map((c) => c.close);
  const minClose = Math.min(...closes);
  const maxClose = Math.max(...closes);
  const pad = (maxClose - minClose) * 0.06;
  const domainMin = minClose - pad;
  const domainMax = maxClose + pad;

  const isUp = candles[candles.length - 1].close >= candles[0].open;
  const strokeColor = isUp ? "#00A86B" : "#DC2626";
  const fillStart = isUp ? "rgba(0,168,107,0.18)" : "rgba(220,38,38,0.18)";

  // Match whale buys to nearest candle time
  const candleSet = new Set(candles.map((c) => c.time));
  const whaleMarkers = whaleBuys.filter((w) => {
    // Find nearest candle within the chart range
    const inRange = w.time >= candles[0].time && w.time <= candles[candles.length - 1].time;
    return inRange;
  });

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={candles} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity={0.25} />
            <stop offset="100%" stopColor={strokeColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="rgba(255,255,255,0.05)"
          vertical={false}
        />
        <XAxis
          dataKey="time"
          tickFormatter={(v) => fmtTime(v, timeframe)}
          tick={{ fontFamily: "monospace", fontSize: 10, fill: "#60608A" }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={40}
        />
        <YAxis
          domain={[domainMin, domainMax]}
          tickFormatter={fmtPrice}
          tick={{ fontFamily: "monospace", fontSize: 10, fill: "#60608A" }}
          axisLine={false}
          tickLine={false}
          width={64}
          tickCount={5}
        />
        <Tooltip content={<ChartTooltip timeframe={timeframe} />} />
        {/* Whale buy markers */}
        {whaleMarkers.map((w, i) => (
          <ReferenceLine
            key={i}
            x={w.time}
            stroke={w.smart_money ? "#0891B2" : "#F59E0B"}
            strokeWidth={1.5}
            strokeDasharray="4 2"
            label={{
              value: "🐋",
              position: "top",
              fontSize: 11,
              fontFamily: "monospace",
            }}
          />
        ))}
        <Area
          type="monotone"
          dataKey="close"
          stroke={strokeColor}
          strokeWidth={2}
          fill="url(#priceGrad)"
          dot={false}
          activeDot={{ r: 4, strokeWidth: 0, fill: strokeColor }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Skeleton() {
  return (
    <div className="animate-pulse flex flex-col gap-4">
      <div className="h-8 bg-border rounded w-1/3" />
      <div className="h-4 bg-border rounded w-1/4" />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-40 bg-border rounded-lg" />
        ))}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function TokenPage() {
  const params = useParams();
  const address = params.address as string;

  const [report, setReport] = useState<MiniReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Chart state
  const [timeframe, setTimeframe] = useState<Timeframe>("7D");
  const [candles, setCandles] = useState<OhlcvCandle[]>([]);
  const [whaleBuys, setWhaleBuys] = useState<WhaleBuy[]>([]);
  const [chartLoading, setChartLoading] = useState(false);

  const fetchReport = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/tokens/${address}/mini-report`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [address]);

  const fetchChart = useCallback(
    (tf: Timeframe) => {
      setChartLoading(true);
      Promise.all([
        fetch(`${API_BASE}/api/tokens/${address}/ohlcv?timeframe=${tf}`).then((r) =>
          r.ok ? r.json() : []
        ),
        fetch(`${API_BASE}/api/tokens/${address}/whale-buys`).then((r) =>
          r.ok ? r.json() : []
        ),
      ])
        .then(([c, w]) => {
          setCandles(c as OhlcvCandle[]);
          setWhaleBuys(w as WhaleBuy[]);
        })
        .catch(() => {
          setCandles([]);
          setWhaleBuys([]);
        })
        .finally(() => setChartLoading(false));
    },
    [address]
  );

  useEffect(() => {
    if (address) {
      fetchReport();
      fetchChart("7D");
    }
  }, [address, fetchReport, fetchChart]);

  const handleTimeframe = (tf: Timeframe) => {
    setTimeframe(tf);
    fetchChart(tf);
  };

  const symbol = report?.symbol || address.slice(0, 8);
  const momColor =
    report?.momentum_24h == null
      ? "text-muted-foreground"
      : report.momentum_24h >= 0
      ? "text-buy"
      : "text-sell";

  return (
    <div className="min-h-screen flex flex-col">
      {/* Nav */}
      <header className="border-b border-border px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
          <Link href="/" className="font-mono text-sm font-semibold tracking-widest text-foreground hover:text-buy transition-colors">
            ZENTRYX
          </Link>
        </div>
        <nav className="hidden sm:flex items-center gap-6 font-mono text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground transition-colors">LEADERBOARD</Link>
          <Link href="/live" className="hover:text-foreground transition-colors">LIVE FEED</Link>
          <Link href="/movers" className="hover:text-foreground transition-colors">MOVERS</Link>
          <Link href="/heatmap" className="hover:text-foreground transition-colors">HEATMAP</Link>
        </nav>
      </header>

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-4xl mx-auto w-full">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground mb-6">
          <Link href="/" className="hover:text-foreground transition-colors">HOME</Link>
          <span>/</span>
          <Link href="/live" className="hover:text-foreground transition-colors">LIVE FEED</Link>
          <span>/</span>
          <span className="text-foreground">{symbol}</span>
        </div>

        {loading ? (
          <Skeleton />
        ) : error ? (
          <div className="rounded-lg border border-border bg-card p-10 text-center flex flex-col items-center gap-4">
            <p className="font-mono text-sm text-muted-foreground">Failed to load token data — {error}</p>
            <button
              onClick={fetchReport}
              className="font-mono text-xs border border-border rounded px-4 py-2 hover:text-foreground hover:border-foreground/50 transition-colors text-muted-foreground"
            >
              RETRY
            </button>
          </div>
        ) : !report ? null : (
          <>
            {/* Hero */}
            <div className="mb-8">
              <div className="flex items-center gap-4 flex-wrap">
                <h1 className="font-mono text-2xl font-bold text-foreground tracking-wider">
                  ${symbol}
                </h1>
                {report.momentum_24h != null && (
                  <span className={`font-mono text-sm font-semibold ${momColor}`}>
                    {report.momentum_24h >= 0 ? "▲" : "▼"}{" "}
                    {report.momentum_24h >= 0 ? "+" : ""}
                    {report.momentum_24h.toFixed(2)}%
                  </span>
                )}
                {report.smart_money_flag && (
                  <span className="font-mono text-xs text-cyan border border-cyan/30 rounded px-2 py-0.5">
                    ◆ SMART MONEY
                  </span>
                )}
              </div>
              <div className="flex items-center gap-6 mt-2 flex-wrap">
                {report.price != null && (
                  <span className="font-mono text-sm text-muted-foreground">
                    PRICE <span className="text-foreground font-semibold">{fmtUsd(report.price)}</span>
                  </span>
                )}
                {report.market_cap != null && (
                  <span className="font-mono text-sm text-muted-foreground">
                    MCAP <span className="text-foreground font-semibold">{fmtUsd(report.market_cap)}</span>
                  </span>
                )}
              </div>
              <div className="mt-2 font-mono text-xs text-muted-foreground break-all">
                {address}
              </div>
            </div>

            {/* 2×2 Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
              {/* Security */}
              <GridCard title="SECURITY">
                <div className="flex flex-col items-center gap-4">
                  <SecurityRadial score={report.security_score} />
                  <div className="w-full">
                    <StatRow
                      label="HONEYPOT"
                      value={report.is_honeypot == null ? "—" : report.is_honeypot ? "YES ⚠" : "CLEAN ✓"}
                      valueClass={report.is_honeypot ? "text-sell" : "text-buy"}
                    />
                    <StatRow
                      label="SMART MONEY"
                      value={report.smart_money_flag ? "YES ✓" : "NO"}
                      valueClass={report.smart_money_flag ? "text-cyan" : "text-muted-foreground"}
                    />
                  </div>
                </div>
              </GridCard>

              {/* Market */}
              <GridCard title="MARKET">
                <StatRow label="PRICE" value={report.price != null ? fmtUsd(report.price) : "—"} />
                <StatRow label="MARKET CAP" value={fmtUsd(report.market_cap)} />
                <StatRow label="24H VOLUME" value={fmtUsd(report.volume_24h)} />
                <StatRow
                  label="24H MOMENTUM"
                  value={
                    report.momentum_24h != null
                      ? `${report.momentum_24h >= 0 ? "+" : ""}${report.momentum_24h.toFixed(2)}%`
                      : "—"
                  }
                  valueClass={momColor}
                />
              </GridCard>

              {/* Liquidity & Holders */}
              <GridCard title="LIQUIDITY & HOLDERS">
                <StatRow label="TOTAL LIQUIDITY" value={fmtUsd(report.total_liquidity_usd)} />
                <StatRow label="HOLDER COUNT" value={fmtNum(report.holder_count)} />
                <div className="pt-3">
                  <p className="font-mono text-xs text-muted-foreground mb-2">BUY / SELL SPLIT</p>
                  <BuySellPie ratio={report.buy_sell_ratio} />
                </div>
              </GridCard>

              {/* Risk Overview */}
              <GridCard title="RISK OVERVIEW">
                <div className="flex flex-col gap-3">
                  {/* Score bar */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono text-xs text-muted-foreground">SCORE</span>
                      <span className="font-mono text-xs" style={{ color: secColor(report.security_score) }}>
                        {report.security_score != null ? `${report.security_score.toFixed(0)}/100` : "—"}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-border overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${report.security_score ?? 0}%`,
                          backgroundColor: secColor(report.security_score),
                        }}
                      />
                    </div>
                  </div>

                  {/* Color legend */}
                  <div className="flex flex-wrap items-center gap-3 font-mono text-xs text-muted-foreground">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-sell inline-block" /> 0-40 RISKY</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-500 inline-block" /> 40-70 OK</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-buy inline-block" /> 70+ SAFE</span>
                  </div>

                  <div className="pt-1">
                    <StatRow
                      label="RISK RATING"
                      value={secLabel(report.security_score)}
                      valueClass={
                        report.security_score == null
                          ? "text-muted-foreground"
                          : report.security_score >= 70
                          ? "text-buy"
                          : report.security_score >= 40
                          ? "text-yellow-400"
                          : "text-sell"
                      }
                    />
                  </div>
                </div>
              </GridCard>
            </div>

            {/* ── OHLCV Price Chart ─────────────────────────────────────── */}
            <div className="rounded-lg border border-border bg-card p-4 mb-6">
              {/* Header row */}
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <div className="flex items-center gap-3">
                  <p className="font-mono text-xs text-muted-foreground tracking-widest">PRICE CHART</p>
                  {whaleBuys.length > 0 && (
                    <span className="font-mono text-xs text-cyan border border-cyan/30 rounded px-2 py-0.5">
                      🐋 {whaleBuys.length} whale buy{whaleBuys.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>
                {/* Timeframe toggle */}
                <div className="flex items-center gap-1 bg-muted/40 rounded-md p-0.5">
                  {(["1D", "7D", "30D"] as Timeframe[]).map((tf) => (
                    <button
                      key={tf}
                      onClick={() => handleTimeframe(tf)}
                      className={`font-mono text-xs px-3 py-1 rounded transition-all duration-150 ${
                        timeframe === tf
                          ? "bg-card text-foreground shadow-sm border border-border/60"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>

              {/* Chart */}
              {chartLoading ? (
                <div className="h-56 flex items-center justify-center">
                  <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
                    <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
                    LOADING CHART...
                  </div>
                </div>
              ) : (
                <OhlcvChart candles={candles} whaleBuys={whaleBuys} timeframe={timeframe} />
              )}

              {/* Legend */}
              {whaleBuys.length > 0 && (
                <div className="flex items-center gap-4 mt-3 pt-3 border-t border-border/40">
                  <span className="font-mono text-xs text-muted-foreground">MARKERS:</span>
                  <span className="flex items-center gap-1.5 font-mono text-xs text-cyan">
                    <span className="inline-block w-4 border-t-2 border-dashed border-cyan" /> Smart money buy
                  </span>
                  <span className="flex items-center gap-1.5 font-mono text-xs text-yellow-400">
                    <span className="inline-block w-4 border-t-2 border-dashed border-yellow-400" /> Whale buy
                  </span>
                </div>
              )}
            </div>

            {/* Links */}
            <div className="flex flex-wrap gap-3">
              <a
                href={`https://solscan.io/token/${address}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-muted-foreground hover:text-cyan border border-border hover:border-cyan/40 rounded px-4 py-2 transition-colors"
              >
                SOLSCAN →
              </a>
              <a
                href={`https://jup.ag/swap/SOL-${address}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-muted-foreground hover:text-buy border border-border hover:border-buy/40 rounded px-4 py-2 transition-colors"
              >
                TRADE ON JUPITER →
              </a>
              <button
                onClick={() => navigator.clipboard.writeText(address)}
                className="font-mono text-xs text-muted-foreground hover:text-foreground border border-border rounded px-4 py-2 transition-colors"
              >
                COPY ADDRESS
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
