"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type TrendingToken = {
  rank: number;
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  price: number;
  price_change_24h: number;
  volume_24h_usd: number;
  volume_change_24h: number;
  liquidity: number;
  market_cap: number;
  smart_buy_count: number;
  smart_score: number;
};

function fmtUsd(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "$0";
  if (Math.abs(n) >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n > 0) return `$${n.toPrecision(3)}`;
  return "$0";
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "0.0%";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function pctColor(n: number | null | undefined): string {
  if (!n) return "text-muted-foreground";
  if (n > 0) return "text-buy";
  if (n < 0) return "text-sell";
  return "text-muted-foreground";
}

function TokenLogo({ uri, symbol }: { uri: string; symbol: string }) {
  if (!uri) {
    return (
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-[10px] font-bold text-muted-foreground">
        {symbol.slice(0, 2)}
      </div>
    );
  }
  return (
    <div className="relative h-7 w-7 shrink-0 overflow-hidden rounded-full bg-muted">
      <Image src={uri} alt={symbol} fill className="object-cover" unoptimized />
    </div>
  );
}

export default function TrendingPage() {
  const [tokens, setTokens] = useState<TrendingToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchTrending = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/trending`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as TrendingToken[];
      setTokens(Array.isArray(raw) ? raw : []);
      setLastRefresh(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrending();
    const interval = setInterval(fetchTrending, 45_000);
    return () => clearInterval(interval);
  }, [fetchTrending]);

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="trending" />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-mono text-2xl font-bold tracking-wide text-foreground">Trending Tokens</h1>
            <p className="font-mono text-xs text-muted-foreground">Top tokens by 24h volume</p>
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
              suppressHydrationWarning
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 font-mono text-xs text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground disabled:opacity-50"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              REFRESH
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-border bg-card p-5 font-mono text-xs text-muted-foreground">
            Failed to load trending feed: {error}
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
            No trending data available
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card/60">
            <div className="hidden grid-cols-[44px_1fr_110px_90px_110px_90px] gap-2 border-b border-border/60 px-3 py-2 font-mono text-[10px] tracking-widest text-muted-foreground md:grid">
              <span>RANK</span>
              <span>TOKEN</span>
              <span className="text-right">PRICE</span>
              <span className="text-right">24H</span>
              <span className="text-right">VOLUME</span>
              <span className="text-right">VOL CHG</span>
            </div>

            {tokens.map((t) => (
              <Link
                key={t.address}
                href={`/token/${t.address}`}
                className="grid grid-cols-[44px_1fr_90px] items-center gap-2 border-b border-border/50 px-3 py-3 transition-colors hover:bg-muted/30 md:grid-cols-[44px_1fr_110px_90px_110px_90px]"
              >
                <span className="font-mono text-xs text-muted-foreground">#{t.rank}</span>
                <div className="flex min-w-0 items-center gap-2">
                  <TokenLogo uri={t.logo_uri} symbol={t.symbol} />
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm font-semibold text-foreground">{t.symbol}</p>
                    <p className="truncate font-mono text-[10px] text-muted-foreground">{t.name || t.address.slice(0, 8)}</p>
                  </div>
                </div>
                <p className="text-right font-mono text-xs text-foreground">{fmtUsd(t.price)}</p>
                <p className={`hidden text-right font-mono text-xs md:block ${pctColor(t.price_change_24h)}`}>{fmtPct(t.price_change_24h)}</p>
                <p className="hidden text-right font-mono text-xs text-foreground md:block">{fmtUsd(t.volume_24h_usd)}</p>
                <p className={`hidden text-right font-mono text-xs md:block ${pctColor(t.volume_change_24h)}`}>{fmtPct(t.volume_change_24h)}</p>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
