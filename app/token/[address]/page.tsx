"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
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
        <ResponsiveContainer width="100%" height="100%">
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
        <ResponsiveContainer width="100%" height="100%">
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

  const fetchReport = () => {
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
  };

  useEffect(() => {
    if (address) fetchReport();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address]);

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
        <nav className="flex items-center gap-6 font-mono text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground transition-colors">LEADERBOARD</Link>
          <Link href="/live" className="hover:text-foreground transition-colors">LIVE FEED</Link>
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
                      value={report.smart_money_flag ? "YES" : "NO"}
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
                  <div className="flex items-center gap-4 font-mono text-xs text-muted-foreground">
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
