"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type Mover = {
  address: string;
  symbol: string;
  name: string;
  price: number;
  price_change_24h: number;
  volume_24h_usd: number;
  liquidity: number;
  market_cap: number;
  logo_uri: string;
};

type MoversData = {
  gainers: Mover[];
  losers: Mover[];
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toPrecision(4)}`;
}

function fmtChange(n: number): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function MoverRow({ mover, rank, side }: { mover: Mover; rank: number; side: "gain" | "loss" }) {
  const isGain = side === "gain";
  const changeColor = isGain ? "text-buy" : "text-sell";
  const changeBg = isGain ? "bg-buy/10 border-buy/20" : "bg-sell/10 border-sell/20";

  return (
    <Link
      href={`/token/${mover.address}`}
      className="group flex items-center gap-3 px-4 py-3 rounded-lg border border-border/50 bg-card/60
                 hover:bg-card hover:border-border hover:shadow-sm transition-all duration-150"
    >
      {/* Rank */}
      <span className="font-mono text-xs text-muted-foreground w-5 text-center shrink-0">
        {rank}
      </span>

      {/* Logo / fallback */}
      <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 overflow-hidden">
        {mover.logo_uri ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mover.logo_uri}
            alt={mover.symbol}
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <span className="font-mono text-xs font-bold text-muted-foreground">
            {mover.symbol.slice(0, 2).toUpperCase()}
          </span>
        )}
      </div>

      {/* Symbol + name */}
      <div className="flex-1 min-w-0">
        <p className="font-mono text-sm font-semibold text-foreground group-hover:text-buy transition-colors truncate">
          ${mover.symbol}
        </p>
        {mover.name && mover.name !== mover.symbol && (
          <p className="font-mono text-xs text-muted-foreground truncate">{mover.name}</p>
        )}
      </div>

      {/* Price */}
      <div className="text-right shrink-0 hidden sm:block">
        <p className="font-mono text-xs text-foreground">{fmtUsd(mover.price)}</p>
        <p className="font-mono text-xs text-muted-foreground">
          Vol {fmtUsd(mover.volume_24h_usd)}
        </p>
      </div>

      {/* Change badge */}
      <div className={`shrink-0 rounded border px-2.5 py-1 ${changeBg}`}>
        <span className={`font-mono text-sm font-bold ${changeColor}`}>
          {fmtChange(mover.price_change_24h)}
        </span>
      </div>

      <span className="text-muted-foreground group-hover:text-foreground transition-colors text-xs shrink-0">→</span>
    </Link>
  );
}

function TableSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[...Array(8)].map((_, i) => (
        <div key={i} className="h-14 rounded-lg bg-muted/40 animate-pulse" />
      ))}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-40 font-mono text-xs text-muted-foreground gap-2">
      <span className="text-2xl">—</span>
      <span>{label}</span>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function MoversPage() {
  const [data, setData] = useState<MoversData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchMovers = () => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/movers`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: MoversData) => {
        setData(d);
        setLastRefresh(new Date());
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchMovers();
  }, []);

  const totalGainers = data?.gainers.length ?? 0;
  const totalLosers = data?.losers.length ?? 0;

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="movers" />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-5xl mx-auto w-full">

        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="font-mono text-2xl font-bold text-foreground tracking-wide">
                Gainers &amp; Losers
              </h1>
              <p className="font-mono text-xs text-muted-foreground mt-1">
                Top price movers from the most active tokens — 24h
              </p>
            </div>
            <div className="flex items-center gap-3">
              {lastRefresh && (
                <span className="font-mono text-xs text-muted-foreground">
                  Updated {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
              <button
                onClick={fetchMovers}
                disabled={loading}
                className="font-mono text-xs border border-border rounded px-4 py-2 text-muted-foreground
                           hover:text-foreground hover:border-foreground/40 transition-colors disabled:opacity-40"
              >
                {loading ? "LOADING..." : "↻ REFRESH"}
              </button>
            </div>
          </div>

          {/* Summary stats */}
          {data && !loading && (
            <div className="flex items-center gap-6 mt-4">
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="h-2 w-2 rounded-full bg-buy" />
                <span className="text-muted-foreground">{totalGainers} gainers</span>
              </div>
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="h-2 w-2 rounded-full bg-sell" />
                <span className="text-muted-foreground">{totalLosers} losers</span>
              </div>
              {data.gainers[0] && (
                <div className="font-mono text-xs text-muted-foreground">
                  Top gainer:{" "}
                  <span className="text-buy font-semibold">
                    ${data.gainers[0].symbol} +{data.gainers[0].price_change_24h.toFixed(1)}%
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-sm text-muted-foreground mb-6">
            Failed to load movers — {error}
            <button
              onClick={fetchMovers}
              className="ml-4 text-xs text-foreground underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}

        {/* Two-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Gainers */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 pb-1 border-b border-border/60">
              <span className="h-2 w-2 rounded-full bg-buy" />
              <h2 className="font-mono text-sm font-semibold text-buy tracking-widest">TOP GAINERS</h2>
              <span className="font-mono text-xs text-muted-foreground ml-auto">24H CHANGE</span>
            </div>
            {loading ? (
              <TableSkeleton />
            ) : !data?.gainers.length ? (
              <EmptyState label="No gainers data" />
            ) : (
              data.gainers.map((m, i) => (
                <MoverRow key={m.address} mover={m} rank={i + 1} side="gain" />
              ))
            )}
          </div>

          {/* Losers */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 pb-1 border-b border-border/60">
              <span className="h-2 w-2 rounded-full bg-sell" />
              <h2 className="font-mono text-sm font-semibold text-sell tracking-widest">TOP LOSERS</h2>
              <span className="font-mono text-xs text-muted-foreground ml-auto">24H CHANGE</span>
            </div>
            {loading ? (
              <TableSkeleton />
            ) : !data?.losers.length ? (
              <EmptyState label="No losers data" />
            ) : (
              data.losers.map((m, i) => (
                <MoverRow key={m.address} mover={m} rank={i + 1} side="loss" />
              ))
            )}
          </div>
        </div>

        {/* Footer note */}
        <p className="font-mono text-xs text-muted-foreground text-center mt-10">
          Data sourced from Birdeye — top 25 tokens by 24h volume, sorted by price change.
          Refresh to get latest prices.
        </p>
      </main>
    </div>
  );
}
