"use client";

import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type RiskLevel = "SAFE" | "RISKY" | "DANGER" | "UNKNOWN";

type NewListing = {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  liquidity: number;
  source: string;
  age_hours: number;
  freezeable: boolean;
  mutable_metadata: boolean;
  transfer_fee: boolean;
  top10_holder_pct: number;
  risk_level: RiskLevel;
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtAge(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m ago`;
  if (hours < 24) return `${hours.toFixed(1)}h ago`;
  return `${(hours / 24).toFixed(1)}d ago`;
}

function RiskBadge({ level }: { level: RiskLevel }) {
  const styles: Record<RiskLevel, string> = {
    SAFE: "border-buy/30 bg-buy/10 text-buy",
    RISKY: "border-yellow-400/30 bg-yellow-400/10 text-yellow-400",
    DANGER: "border-sell/30 bg-sell/10 text-sell",
    UNKNOWN: "border-border bg-muted/20 text-muted-foreground",
  };
  return (
    <span className={`rounded border px-2 py-0.5 font-mono text-xs font-semibold ${styles[level]}`}>
      {level}
    </span>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ListingRow({ token, rank }: { token: NewListing; rank: number }) {
  return (
    <Link
      href={`/token/${token.address}`}
      className="group flex items-center gap-3 px-4 py-3 rounded-lg border border-border/50 bg-card/60 hover:bg-card hover:border-border hover:shadow-sm transition-all duration-150"
    >
      {/* Rank */}
      <span className="font-mono text-xs text-muted-foreground w-5 text-center shrink-0">{rank}</span>

      {/* Logo */}
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

      {/* Symbol + source */}
      <div className="flex-1 min-w-0">
        <p className="font-mono text-sm font-semibold text-foreground group-hover:text-buy transition-colors truncate">
          ${token.symbol}
        </p>
        <p className="font-mono text-xs text-muted-foreground truncate">
          {token.source || token.name || "—"}
        </p>
      </div>

      {/* Age */}
      <div className="text-right shrink-0 hidden sm:block">
        <p className="font-mono text-xs text-foreground">{fmtAge(token.age_hours)}</p>
        <p className="font-mono text-xs text-muted-foreground">AGE</p>
      </div>

      {/* Liquidity */}
      <div className="text-right shrink-0 hidden sm:block">
        <p className="font-mono text-xs text-foreground">{fmtUsd(token.liquidity)}</p>
        <p className="font-mono text-xs text-muted-foreground">LIQUIDITY</p>
      </div>

      {/* Flags */}
      <div className="hidden md:flex items-center gap-1 shrink-0">
        {token.freezeable && (
          <span title="Freezeable mint" className="rounded bg-sell/10 border border-sell/20 px-1.5 py-0.5 font-mono text-xs text-sell">
            FREEZE
          </span>
        )}
        {token.transfer_fee && (
          <span title="Transfer fee enabled" className="rounded bg-yellow-400/10 border border-yellow-400/20 px-1.5 py-0.5 font-mono text-xs text-yellow-400">
            FEE
          </span>
        )}
        {token.mutable_metadata && (
          <span title="Mutable metadata" className="rounded bg-muted/40 border border-border px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
            MUT
          </span>
        )}
      </div>

      {/* Risk badge */}
      <div className="shrink-0">
        <RiskBadge level={token.risk_level} />
      </div>

      <span className="text-muted-foreground group-hover:text-foreground transition-colors text-xs shrink-0">→</span>
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

export default function NewListingsPage() {
  const [data, setData] = useState<NewListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchListings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/new-listings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setLastRefresh(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchListings();
    // Auto-refresh every 60s — new listings change fast
    const interval = setInterval(fetchListings, 60_000);
    return () => clearInterval(interval);
  }, [fetchListings]);

  const safeCount = data.filter((t) => t.risk_level === "SAFE").length;
  const dangerCount = data.filter((t) => t.risk_level === "DANGER").length;

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="new-listings" />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-4xl mx-auto w-full">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="font-mono text-2xl font-bold text-foreground tracking-wide">
                New Listings
              </h1>
              <p className="font-mono text-xs text-muted-foreground mt-1">
                Recently launched Solana tokens · security-scored · auto-refreshes every 60s
              </p>
            </div>
            <div className="flex items-center gap-3">
              {lastRefresh && (
                <span className="font-mono text-xs text-muted-foreground">
                  {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
              <button
                onClick={fetchListings}
                disabled={loading}
                className="font-mono text-xs border border-border rounded px-4 py-2 text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors disabled:opacity-40"
              >
                {loading ? "LOADING..." : "↻ REFRESH"}
              </button>
            </div>
          </div>

          {/* Risk summary */}
          {!loading && data.length > 0 && (
            <div className="flex items-center gap-6 mt-4 font-mono text-xs">
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-buy" />
                <span className="text-muted-foreground">{safeCount} safe</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-sell" />
                <span className="text-muted-foreground">{dangerCount} danger</span>
              </div>
              <div className="flex items-center gap-2 text-muted-foreground/60">
                <span>FREEZE = mint authority active</span>
                <span>·</span>
                <span>FEE = transfer tax</span>
                <span>·</span>
                <span>MUT = mutable metadata</span>
              </div>
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-border bg-card p-6 text-center font-mono text-sm text-muted-foreground mb-6">
            Failed to load new listings — {error}
            <button onClick={fetchListings} className="ml-4 text-xs text-foreground underline underline-offset-2">
              Retry
            </button>
          </div>
        )}

        {/* Rows */}
        {loading ? (
          <TableSkeleton />
        ) : data.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 font-mono text-xs text-muted-foreground gap-2">
            <span className="text-2xl">—</span>
            <span>No new listings found</span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {data.map((token, i) => (
              <ListingRow key={`${token.address}-${i}`} token={token} rank={i + 1} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
