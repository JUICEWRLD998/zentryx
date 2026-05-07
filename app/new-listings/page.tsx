"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type NewListing = {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  price: number;
  volume_24h_usd: number;
  liquidity: number;
  market_cap: number;
  age_hours: number;
  risk_level: string;
};

function fmtUsd(n: number): string {
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n > 0) return `$${n.toPrecision(3)}`;
  return "$0";
}

function riskColor(risk: string): string {
  if (risk === "DANGER") return "text-sell";
  if (risk === "RISKY") return "text-yellow-500";
  return "text-buy";
}

export default function NewListingsPage() {
  const [tokens, setTokens] = useState<NewListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchNewListings = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/new-listings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as NewListing[];
      setTokens(Array.isArray(raw) ? raw : []);
      setLastRefresh(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNewListings();
    const interval = setInterval(fetchNewListings, 60_000);
    return () => clearInterval(interval);
  }, [fetchNewListings]);

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="new-listings" />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-mono text-2xl font-bold tracking-wide text-foreground">New Listings</h1>
            <p className="font-mono text-xs text-muted-foreground">Recently launched Solana tokens</p>
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="font-mono text-xs text-muted-foreground">
                {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <button
              onClick={fetchNewListings}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 font-mono text-xs text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground disabled:opacity-50"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              REFRESH
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-border bg-card p-5 font-mono text-xs text-muted-foreground">
            Failed to load new listings: {error}
          </div>
        )}

        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded-lg border border-border/40 bg-card/60" />
            ))}
          </div>
        ) : tokens.length === 0 ? (
          <div className="flex h-56 items-center justify-center rounded-lg border border-border bg-card font-mono text-xs text-muted-foreground">
            No new listings available
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card/60">
            <div className="hidden grid-cols-[1fr_100px_100px_100px_100px_80px] gap-2 border-b border-border/60 px-3 py-2 font-mono text-[10px] tracking-widest text-muted-foreground md:grid">
              <span>TOKEN</span>
              <span className="text-right">PRICE</span>
              <span className="text-right">LIQUIDITY</span>
              <span className="text-right">AGE (h)</span>
              <span className="text-right">RISK</span>
              <span className="text-center">ACTION</span>
            </div>

            {tokens.map((t) => (
              <Link
                key={t.address}
                href={`/token/${t.address}`}
                className="grid grid-cols-[1fr_80px] items-center gap-2 border-b border-border/50 px-3 py-3 transition-colors hover:bg-muted/30 md:grid-cols-[1fr_100px_100px_100px_100px_80px]"
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-sm font-semibold text-foreground">{t.symbol}</p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">{t.name || t.address.slice(0, 8)}</p>
                </div>
                <p className="text-right font-mono text-xs text-foreground md:text-sm">{fmtUsd(t.price)}</p>
                <p className="hidden text-right font-mono text-xs text-foreground md:block">{fmtUsd(t.liquidity)}</p>
                <p className="hidden text-center font-mono text-xs text-muted-foreground md:block">{t.age_hours.toFixed(1)}</p>
                <p className={`hidden text-right font-mono text-xs md:block ${riskColor(t.risk_level)}`}>{t.risk_level}</p>
                <p className="text-right font-mono text-xs text-muted-foreground md:text-cyan">→</p>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
