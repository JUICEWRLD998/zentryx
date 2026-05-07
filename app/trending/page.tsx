"use client";

import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type TrendingToken = {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  price: number;
  volume_24h_usd: number;
  liquidity: number;
  market_cap: number;
  smart_buy_count: number;
  smart_score: number;
};

type SortKey = "smart_score" | "volume_24h_usd" | "liquidity";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n > 0) return `$${n.toPrecision(3)}`;
  return "$0";
}

function fmtScore(n: number): string {
  return n.toFixed(1);
}

// ── Sub-components ─────────────────────────────────────────────────────────

function TokenRow({ token, rank }: { token: TrendingToken; rank: number }) {
  const hasWhales = token.smart_buy_count > 0;

  return (
    <Link
      href={`/token/${token.address}`}
      className="group grid grid-cols-[2rem_1fr_auto_auto_auto_auto] sm:grid-cols-[2rem_1fr_auto_auto_auto_auto] items-center gap-3 px-4 py-3 rounded-lg border border-border/50 bg-card/60 hover:bg-card hover:border-border hover:shadow-sm transition-all duration-150"
    >
      {/* Rank */}
      <span className="font-mono text-xs text-muted-foreground text-center">{rank}</span>

      {/* Token identity */}
      <div className="flex items-center gap-2.5 min-w-0">
        <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 overflow-hidden">
          {token.logo_uri ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={token.logo_uri}
              alt={token.symbol}
              className="w-full h-full object-cover"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          ) : (
            <span className="font-mono text-xs font-bold text-muted-foreground">
              {token.symbol.slice(0, 2).toUpperCase()}
            </span>
          )}
        </div>
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold text-foreground group-hover:text-buy transition-colors truncate">
            ${token.symbol}
          </p>
          {token.name && token.name !== token.symbol && (
            <p className="font-mono text-xs text-muted-foreground truncate hidden sm:block">{token.name}</p>
          )}
        </div>
      </div>

      {/* Whale badge */}
      <div className="shrink-0">
        {hasWhales ? (
          <span className="rounded border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-mono text-xs text-cyan whitespace-nowrap">
            ×{token.smart_buy_count}
          </span>
        ) : (
          <span className="font-mono text-xs text-muted-foreground/40">—</span>
        )}
      </div>

      {/* Smart score */}
      <div className="text-right shrink-0 hidden md:block">
        <p className="font-mono text-xs text-foreground font-semibold">{fmtScore(token.smart_score)}</p>
        <p className="font-mono text-xs text-muted-foreground">SCORE</p>
      </div>

      {/* Volume */}
      <div className="text-right shrink-0 hidden sm:block">
        <p className="font-mono text-xs text-foreground">{fmtUsd(token.volume_24h_usd)}</p>
        <p className="font-mono text-xs text-muted-foreground">VOL 24H</p>
      </div>

      {/* Price */}
      <div className="text-right shrink-0">
        <p className="font-mono text-xs text-foreground">{fmtUsd(token.price)}</p>
        <span className="text-muted-foreground text-xs group-hover:text-foreground transition-colors">→</span>
      </div>
    </Link>
  );
}

function TableSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[...Array(10)].map((_, i) => (
        <div key={i} className="h-14 rounded-lg bg-muted/40 animate-pulse" />
      ))}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function TrendingPage() {
  const [data, setData] = useState<TrendingToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("smart_score");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchTrending = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/trending`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setLastRefresh(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTrending(); }, [fetchTrending]);

  const sorted = [...data].sort((a, b) => b[sortKey] - a[sortKey]);
  const whaleCount = data.filter((t) => t.smart_buy_count > 0).length;

  const SORT_TABS: { key: SortKey; label: string }[] = [
    { key: "smart_score", label: "SMART SCORE" },
    { key: "volume_24h_usd", label: "VOLUME" },
    { key: "liquidity", label: "LIQUIDITY" },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="trending" />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-4xl mx-auto w-full">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="font-mono text-2xl font-bold text-foreground tracking-wide">
                Smart Money Trending
              </h1>
              <p className="font-mono text-xs text-muted-foreground mt-1">
                Tokens ranked by whale activity + volume · 48h lookback
              </p>
            </div>
            <div className="flex items-center gap-3">
              {lastRefresh && (
                <span className="font-mono text-xs text-muted-foreground">
                  {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
              <button
                onClick={fetchTrending}
                disabled={loading}
                className="font-mono text-xs border border-border rounded px-4 py-2 text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors disabled:opacity-40"
              >
                {loading ? "LOADING..." : "↻ REFRESH"}
              </button>
            </div>
          </div>

          {/* Stats + sort row */}
          {!loading && data.length > 0 && (
            <div className="flex items-center justify-between flex-wrap gap-3 mt-4">
              <div className="flex items-center gap-6 font-mono text-xs text-muted-foreground">
                <span>{data.length} tokens tracked</span>
                {whaleCount > 0 && (
                  <span className="text-cyan">
                    {whaleCount} with whale activity
                  </span>
                )}
              </div>
              {/* Sort toggle */}
              <div className="flex rounded border border-border overflow-hidden">
                {SORT_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setSortKey(tab.key)}
                    className={`font-mono text-xs px-3 py-1.5 transition-colors ${
                      sortKey === tab.key
                        ? "bg-buy text-background font-semibold"
                        : "text-muted-foreground hover:text-foreground hover:bg-card"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-sm text-muted-foreground mb-6">
            Failed to load trending data — {error}
            <button onClick={fetchTrending} className="ml-4 text-xs text-foreground underline underline-offset-2">
              Retry
            </button>
          </div>
        )}

        {/* Table header */}
        {!loading && sorted.length > 0 && (
          <div className="grid grid-cols-[2rem_1fr_auto_auto_auto_auto] sm:grid-cols-[2rem_1fr_auto_auto_auto_auto] items-center gap-3 px-4 pb-2 mb-1 border-b border-border/40">
            <span className="font-mono text-xs text-muted-foreground">#</span>
            <span className="font-mono text-xs text-muted-foreground">TOKEN</span>
            <span className="font-mono text-xs text-muted-foreground text-right">WHALES</span>
            <span className="font-mono text-xs text-muted-foreground text-right hidden md:block">SCORE</span>
            <span className="font-mono text-xs text-muted-foreground text-right hidden sm:block">VOL 24H</span>
            <span className="font-mono text-xs text-muted-foreground text-right">PRICE</span>
          </div>
        )}

        {/* Rows */}
        {loading ? (
          <TableSkeleton />
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 font-mono text-xs text-muted-foreground gap-2">
            <span className="text-2xl">—</span>
            <span>No trending data available</span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {sorted.map((token, i) => (
              <TokenRow key={token.address} token={token} rank={i + 1} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
