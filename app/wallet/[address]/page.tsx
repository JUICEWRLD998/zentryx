"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface WalletDetail {
  address: string;
  label: string;
  is_tracked: boolean;
  pnl: {
    realized_usd?: number;
    unrealized_usd?: number;
    total_usd?: number;
    win_rate?: number;
    total_trade?: number;
    total_win?: number;
    total_loss?: number;
  };
  net_worth: {
    total_usd?: number;
  };
}

function fmt_usd(n: number | undefined | null): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function StatCard({
  label,
  value,
  sub,
  color = "text-foreground",
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <p className="font-mono text-xs text-muted-foreground tracking-widest mb-2">{label}</p>
      <p className={`font-mono text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="font-mono text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

export default function WalletPage() {
  const { address } = useParams<{ address: string }>();
  const [data, setData] = useState<WalletDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!address) return;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/wallets/${address}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setData(await res.json());
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [address]);

  const shortAddr = address
    ? `${address.slice(0, 6)}...${address.slice(-4)}`
    : "";

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

      <main className="flex-1 px-6 py-8 max-w-5xl mx-auto w-full">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground mb-6">
          <Link href="/" className="hover:text-foreground transition-colors">LEADERBOARD</Link>
          <span>/</span>
          <span className="text-foreground">{data?.label ?? shortAddr}</span>
        </div>

        {loading ? (
          <div className="text-center font-mono text-xs text-muted-foreground animate-pulse py-20">
            LOADING WALLET DATA...
          </div>
        ) : error ? (
          <div className="text-center font-mono text-xs text-sell py-20">{error}</div>
        ) : data ? (
          <>
            {/* Wallet header */}
            <div className="mb-8">
              <h1 className="font-mono text-xl font-bold text-foreground mb-1">
                {data.label}
              </h1>
              <p className="font-mono text-xs text-muted-foreground break-all">{address}</p>
              {data.is_tracked && (
                <span className="mt-2 inline-block rounded border border-buy/40 px-2 py-0.5 font-mono text-xs text-buy bg-buy/10">
                  TRACKED WHALE
                </span>
              )}
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="TOTAL PNL"
                value={fmt_usd(data.pnl.total_usd)}
                color={(data.pnl.total_usd ?? 0) >= 0 ? "text-buy" : "text-sell"}
              />
              <StatCard
                label="REALIZED PNL"
                value={fmt_usd(data.pnl.realized_usd)}
                color={(data.pnl.realized_usd ?? 0) >= 0 ? "text-buy" : "text-sell"}
              />
              <StatCard
                label="WIN RATE"
                value={
                  data.pnl.win_rate != null
                    ? `${(data.pnl.win_rate * 100).toFixed(1)}%`
                    : "—"
                }
                sub={
                  data.pnl.total_win != null && data.pnl.total_loss != null
                    ? `${data.pnl.total_win}W / ${data.pnl.total_loss}L`
                    : undefined
                }
                color={
                  (data.pnl.win_rate ?? 0) >= 0.6
                    ? "text-buy"
                    : (data.pnl.win_rate ?? 0) >= 0.4
                    ? "text-yellow-400"
                    : "text-sell"
                }
              />
              <StatCard
                label="TOTAL TRADES"
                value={data.pnl.total_trade?.toLocaleString() ?? "—"}
              />
            </div>

            {/* Net worth (if available) */}
            {data.net_worth.total_usd != null && (
              <div className="rounded-lg border border-border bg-card p-5 mb-8">
                <p className="font-mono text-xs text-muted-foreground tracking-widest mb-2">
                  CURRENT NET WORTH
                </p>
                <p className="font-mono text-2xl font-bold text-cyan">
                  {fmt_usd(data.net_worth.total_usd)}
                </p>
              </div>
            )}

            {/* Solscan link */}
            <div className="flex gap-4">
              <a
                href={`https://solscan.io/account/${address}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-muted-foreground hover:text-cyan transition-colors border border-border rounded px-3 py-2"
              >
                VIEW ON SOLSCAN →
              </a>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
