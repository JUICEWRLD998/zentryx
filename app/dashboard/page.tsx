"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { NavBar } from "@/components/navbar";
import { Zap, TrendingUp, ArrowRight } from "lucide-react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Wallet {
  rank: number;
  address: string;
  label: string;
  total_pnl: number;
  win_rate: number;
  trade_count: number;
}

interface OverlapWhale {
  address: string;
  label: string;
  value_usd: number;
  allocation_pct: number;
}

interface OverlapToken {
  token_address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  whale_count: number;
  total_usd: number;
  conviction: "EXTREME" | "HIGH" | "MODERATE";
  whales: OverlapWhale[];
}

interface OverlapData {
  tokens: OverlapToken[];
  wallets_analyzed: number;
  generated_at: number;
}

interface SignalPerformer {
  address: string;
  symbol: string;
  entry_usd: number;
  current_price: number;
  return_pct: number;
}

interface SignalStats {
  computed_at: string | null;
  total_signals: number;
  profitable: number;
  win_rate: number;
  avg_return_pct: number;
  top_performers: SignalPerformer[];
}

interface Rotation {
  wallet_label: string;
  from_token: string;
  from_symbol: string;
  to_token: string;
  to_symbol: string;
  from_usd: number;
  to_usd: number;
  detected_at: string;
}

interface RotationData {
  rotations: Rotation[];
  generated_at: number;
}

function fmt_usd(n: number): string {
  if (Math.abs(n) >= 1_000_000)
    return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000)
    return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmt_pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function PnLCell({ value }: { value: number }) {
  const color = value >= 0 ? "text-buy" : "text-sell";
  return <span className={color}>{fmt_usd(value)}</span>;
}

function WinRateBadge({ rate }: { rate: number }) {
  const pct = rate * 100;
  const color =
    pct >= 60
      ? "border-buy/40 text-buy bg-buy/10"
      : pct >= 40
      ? "border-yellow-400/40 text-yellow-400 bg-yellow-400/10"
      : "border-sell/40 text-sell bg-sell/10";
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold font-mono ${color}`}>
      {fmt_pct(rate)}
    </span>
  );
}

export default function Dashboard() {
  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [overlap, setOverlap] = useState<OverlapData | null>(null);
  const [overlapLoading, setOverlapLoading] = useState(true);

  const [signals, setSignals] = useState<SignalStats | null>(null);
  const [signalsLoading, setSignalsLoading] = useState(true);

  const [rotations, setRotations] = useState<RotationData | null>(null);
  const [rotationsLoading, setRotationsLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/wallets`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setWallets(data);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/wallets/overlap`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setOverlap(d))
      .catch(() => {})
      .finally(() => setOverlapLoading(false));
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/stats`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setSignals(d))
      .catch(() => {})
      .finally(() => setSignalsLoading(false));
  }, []);

  useEffect(() => {
    const load = () => {
      fetch(`${API_BASE}/api/rotations`)
        .then((r) => r.ok ? r.json() : null)
        .then((d) => setRotations(d))
        .catch(() => {})
        .finally(() => setRotationsLoading(false));
    };
    load();
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
  }, []);

  const totalPnl = wallets.reduce((s, w) => s + w.total_pnl, 0);
  const bestWinRate = wallets.length
    ? Math.max(...wallets.map((w) => w.win_rate))
    : 0;

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="leaderboard" />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-5xl mx-auto w-full">
        {/* ── Hero stats ── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          {[
            { label: "WHALES TRACKED", value: wallets.length.toString(), color: "text-cyan" },
            {
              label: "TOTAL PNL (7D)",
              value: loading ? "—" : fmt_usd(totalPnl),
              color: totalPnl >= 0 ? "text-buy" : "text-sell",
            },
            {
              label: "BEST WIN RATE",
              value: loading ? "—" : fmt_pct(bestWinRate),
              color: "text-yellow-400",
            },
          ].map(({ label, value, color }) => (
            <div key={label} className="rounded-lg border border-border bg-card p-5">
              <p className="font-mono text-xs text-muted-foreground tracking-widest mb-2">
                {label}
              </p>
              <p className={`font-mono text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>

        {/* ── Leaderboard table ── */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-5 py-3 border-b border-border flex items-center justify-between">
            <h2 className="font-mono text-xs text-muted-foreground tracking-widest">
              WHALE LEADERBOARD
            </h2>
            <span className="font-mono text-xs text-muted-foreground">7D · UPDATED LIVE</span>
          </div>

          {loading ? (
            <div className="p-8 text-center font-mono text-xs text-muted-foreground animate-pulse">
              LOADING...
            </div>
          ) : error ? (
            <div className="p-8 text-center font-mono text-xs text-sell">
              {error}
            </div>
          ) : wallets.length === 0 ? (
            <div className="p-8 text-center font-mono text-xs text-muted-foreground">
              NO WALLETS TRACKED YET — DISCOVERY IN PROGRESS
            </div>
          ) : (
            <div className="overflow-x-auto">
            <table className="w-full min-w-140 font-mono text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground text-xs">
                  <th className="px-5 py-2.5 text-left w-8">#</th>
                  <th className="px-5 py-2.5 text-left">WALLET</th>
                  <th className="px-5 py-2.5 text-right">7D PNL</th>
                  <th className="px-5 py-2.5 text-right">WIN RATE</th>
                  <th className="px-5 py-2.5 text-right">TRADES</th>
                  <th className="px-5 py-2.5 text-right"></th>
                </tr>
              </thead>
              <tbody>
                {wallets.map((w) => (
                  <tr
                    key={w.address}
                    className="border-b border-border/50 hover:bg-secondary/30 transition-colors"
                  >
                    <td className="px-5 py-3 text-muted-foreground">{w.rank}</td>
                    <td className="px-5 py-3">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-foreground font-semibold">{w.label}</span>
                        <span className="text-muted-foreground text-xs">
                          {w.address.slice(0, 6)}...{w.address.slice(-4)}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-right">
                      <PnLCell value={w.total_pnl} />
                    </td>
                    <td className="px-5 py-3 text-right">
                      <WinRateBadge rate={w.win_rate} />
                    </td>
                    <td className="px-5 py-3 text-right text-muted-foreground">
                      {w.trade_count.toLocaleString()}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        href={`/wallet/${w.address}`}
                        className="text-xs text-cyan hover:text-cyan/80 transition-colors"
                      >
                        VIEW →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>

        {/* ── Signal Performance ── */}
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp size={14} className="text-buy" />
            <h2 className="font-mono text-xs text-muted-foreground tracking-widest uppercase">
              Signal Performance
            </h2>
            <span className="rounded-full border border-buy/30 bg-buy/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest text-buy">
              Live Outcomes
            </span>
          </div>

          {signalsLoading ? (
            <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-xs text-muted-foreground animate-pulse">
              COMPUTING SIGNAL STATS...
            </div>
          ) : !signals || signals.total_signals === 0 ? (
            <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-xs text-muted-foreground">
              Signal stats computed every 2h — check back soon.
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-card overflow-hidden">
              {/* Aggregate row */}
              <div className="grid grid-cols-3 divide-x divide-border border-b border-border">
                {[
                  {
                    label: "WIN RATE",
                    value: `${signals.win_rate.toFixed(1)}%`,
                    color: signals.win_rate >= 55 ? "text-buy" : signals.win_rate >= 40 ? "text-yellow-400" : "text-sell",
                  },
                  {
                    label: "SIGNALS TRACKED",
                    value: `${signals.profitable}/${signals.total_signals}`,
                    color: "text-foreground",
                  },
                  {
                    label: "AVG RETURN",
                    value: `${signals.avg_return_pct >= 0 ? "+" : ""}${signals.avg_return_pct.toFixed(2)}%`,
                    color: signals.avg_return_pct >= 0 ? "text-buy" : "text-sell",
                  },
                ].map(({ label, value, color }) => (
                  <div key={label} className="px-5 py-4">
                    <p className="font-mono text-[10px] text-muted-foreground tracking-widest mb-1">{label}</p>
                    <p className={`font-mono text-xl font-bold ${color}`}>{value}</p>
                  </div>
                ))}
              </div>
              {/* Top performers */}
              {signals.top_performers.length > 0 && (
                <div className="px-5 py-3">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground mb-2">
                    TOP PERFORMERS
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {signals.top_performers.slice(0, 3).map((p) => (
                      <Link
                        key={p.address}
                        href={`/token/${p.address}`}
                        className="flex items-center justify-between rounded border border-border/50 bg-background/40 px-3 py-2 hover:border-buy/30 hover:bg-buy/5 transition-colors"
                      >
                        <span className="font-mono text-xs font-semibold text-foreground">
                          ${p.symbol}
                        </span>
                        <span className={`font-mono text-xs font-bold ${p.return_pct >= 0 ? "text-buy" : "text-sell"}`}>
                          {p.return_pct >= 0 ? "+" : ""}{p.return_pct.toFixed(2)}%
                        </span>
                      </Link>
                    ))}
                  </div>
                  {signals.computed_at && (
                    <p className="font-mono text-[9px] text-muted-foreground/50 mt-2">
                      Updated {new Date(signals.computed_at).toLocaleTimeString()}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Whale Conviction Zones ── */}
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-4">
            <Zap size={14} className="text-cyan" />
            <h2 className="font-mono text-xs text-muted-foreground tracking-widest uppercase">
              Whale Conviction Zones
            </h2>
            <span className="rounded-full border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest text-cyan">
              Token Overlap Matrix
            </span>
            {overlap && (
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {overlap.wallets_analyzed} wallets analyzed
              </span>
            )}
          </div>

          {overlapLoading ? (
            <div className="rounded-lg border border-border bg-card p-8 text-center font-mono text-xs text-muted-foreground animate-pulse">
              COMPUTING OVERLAP...
            </div>
          ) : !overlap || overlap.tokens.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-8 text-center font-mono text-xs text-muted-foreground">
              No shared positions found yet — portfolio data updates every 10 min.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {overlap.tokens.slice(0, 12).map((token) => {
                const isExtreme = token.conviction === "EXTREME";
                const isHigh = token.conviction === "HIGH";
                return (
                  <Link
                    key={token.token_address}
                    href={`/token/${token.token_address}`}
                    className={`group rounded-xl border p-4 transition-all hover:scale-[1.01] block ${
                      isExtreme
                        ? "border-yellow-400/40 bg-yellow-400/5 hover:border-yellow-400/60"
                        : isHigh
                        ? "border-cyan/30 bg-cyan/5 hover:border-cyan/50"
                        : "border-border bg-card hover:border-border/80"
                    }`}
                  >
                    {/* Token header */}
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-bold text-foreground group-hover:text-cyan transition-colors truncate">
                          {token.symbol}
                        </p>
                        {token.name && (
                          <p className="font-mono text-[10px] text-muted-foreground truncate">
                            {token.name}
                          </p>
                        )}
                      </div>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest ${
                        isExtreme
                          ? "bg-yellow-400/20 text-yellow-400"
                          : isHigh
                          ? "bg-cyan/20 text-cyan"
                          : "bg-muted text-muted-foreground"
                      }`}>
                        {isExtreme ? "⚡ EXTREME" : isHigh ? "HIGH" : "MODERATE"}
                      </span>
                    </div>

                    {/* Stats row */}
                    <div className="flex items-center gap-3 mb-3">
                      <div>
                        <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">Whales</p>
                        <p className={`font-mono text-lg font-bold ${isExtreme ? "text-yellow-400" : "text-cyan"}`}>
                          {token.whale_count}
                        </p>
                      </div>
                      <div className="h-8 w-px bg-border" />
                      <div>
                        <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">Combined</p>
                        <p className="font-mono text-sm font-semibold text-foreground">
                          {token.total_usd >= 1_000_000
                            ? `$${(token.total_usd / 1_000_000).toFixed(1)}M`
                            : token.total_usd >= 1_000
                            ? `$${(token.total_usd / 1_000).toFixed(0)}K`
                            : `$${token.total_usd.toFixed(0)}`}
                        </p>
                      </div>
                    </div>

                    {/* Whale labels */}
                    <div className="flex flex-wrap gap-1">
                      {token.whales.map((w) => (
                        <span
                          key={w.address}
                          className="rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[9px] text-muted-foreground"
                          title={`${w.label}: $${w.value_usd.toLocaleString()}`}
                        >
                          {w.label}
                        </span>
                      ))}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Recent Whale Rotations ── */}
        <div className="mt-8 mb-4">
          <div className="flex items-center gap-2 mb-4">
            <ArrowRight size={14} className="text-yellow-400" />
            <h2 className="font-mono text-xs text-muted-foreground tracking-widest uppercase">
              Recent Whale Rotations
            </h2>
            <span className="rounded-full border border-yellow-400/30 bg-yellow-400/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-widest text-yellow-400">
              Exit → Entry
            </span>
          </div>

          {rotationsLoading ? (
            <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-xs text-muted-foreground animate-pulse">
              SCANNING ROTATIONS...
            </div>
          ) : !rotations || rotations.rotations.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-xs text-muted-foreground">
              No rotations detected in the last 48h — check back as whale activity picks up.
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-card overflow-hidden divide-y divide-border/50">
              {rotations.rotations.slice(0, 8).map((r, idx) => {
                const ago = Math.round(
                  (Date.now() - new Date(r.detected_at).getTime()) / 60_000
                );
                const agoStr = ago < 60 ? `${ago}m ago` : `${Math.round(ago / 60)}h ago`;
                return (
                  <div
                    key={`${r.wallet_label}-${r.from_token}-${r.to_token}-${idx}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-xs font-mono"
                  >
                    <span className="font-semibold text-foreground shrink-0">{r.wallet_label}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Link
                        href={`/token/${r.from_token}`}
                        className="rounded border border-sell/30 bg-sell/10 px-1.5 py-0.5 text-sell hover:border-sell/60 transition-colors"
                      >
                        ${r.from_symbol}
                      </Link>
                      <span className="text-muted-foreground">→</span>
                      <Link
                        href={`/token/${r.to_token}`}
                        className="rounded border border-buy/30 bg-buy/10 px-1.5 py-0.5 text-buy hover:border-buy/60 transition-colors"
                      >
                        ${r.to_symbol}
                      </Link>
                    </div>
                    <span className="text-muted-foreground shrink-0">
                      {fmt_usd(r.from_usd)} → {fmt_usd(r.to_usd)}
                    </span>
                    <span className="ml-auto text-muted-foreground/60 shrink-0">{agoStr}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
