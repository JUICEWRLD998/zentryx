"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

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

  const totalPnl = wallets.reduce((s, w) => s + w.total_pnl, 0);
  const bestWinRate = wallets.length
    ? Math.max(...wallets.map((w) => w.win_rate))
    : 0;

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Nav ── */}
      <header className="border-b border-border px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
          <Link href="/" className="font-mono text-sm font-semibold tracking-widest text-foreground hover:text-buy transition-colors">
            ZENTRYX
          </Link>
        </div>
        <nav className="hidden sm:flex items-center gap-6 font-mono text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground transition-colors">HOME</Link>
          <span className="text-foreground border-b border-buy pb-0.5">DASHBOARD</span>
          <Link href="/live" className="hover:text-foreground transition-colors">LIVE FEED</Link>
        </nav>
        <ThemeToggle />
      </header>

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
      </main>
    </div>
  );
}
