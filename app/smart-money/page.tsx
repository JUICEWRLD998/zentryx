"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { NavBar } from "@/components/navbar";
import { RefreshCw, Zap, TrendingUp, TrendingDown, Minus } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────

type Signal = "BUY" | "SELL" | "NEUTRAL";
type FilterValue = "ALL" | Signal;

interface SmartMoneyToken {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  signal: Signal;
  buy_usd: number;
  sell_usd: number;
  net_usd: number;
}

interface HeatmapData {
  tokens: SmartMoneyToken[];
  generated_at: number;
}

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (!isFinite(n) || n === 0) return "$0";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

// ──────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────

function SignalBadge({ signal }: { signal: Signal }) {
  if (signal === "BUY") {
    return (
      <span className="flex items-center gap-1 w-fit rounded-full bg-buy/15 border border-buy/30 px-2.5 py-0.5 font-mono text-[10px] font-bold text-buy uppercase tracking-wider">
        <TrendingUp size={8} />
        Accumulating
      </span>
    );
  }
  if (signal === "SELL") {
    return (
      <span className="flex items-center gap-1 w-fit rounded-full bg-sell/15 border border-sell/30 px-2.5 py-0.5 font-mono text-[10px] font-bold text-sell uppercase tracking-wider">
        <TrendingDown size={8} />
        Distributing
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 w-fit rounded-full bg-muted/30 border border-border/40 px-2.5 py-0.5 font-mono text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
      <Minus size={8} />
      Neutral
    </span>
  );
}

function TokenCard({ token }: { token: SmartMoneyToken }) {
  const hasVolume = token.buy_usd > 0 || token.sell_usd > 0;

  const borderCls =
    token.signal === "BUY"
      ? "border-buy/20 hover:border-buy/50"
      : token.signal === "SELL"
      ? "border-sell/20 hover:border-sell/50"
      : "border-border/40 hover:border-border/70";

  const hoverBg =
    token.signal === "BUY"
      ? "hover:bg-buy/5"
      : token.signal === "SELL"
      ? "hover:bg-sell/5"
      : "hover:bg-muted/10";

  return (
    <Link
      href={`/token/${token.address}`}
      className={`flex flex-col gap-3 rounded-xl border bg-card p-4 transition-all ${borderCls} ${hoverBg}`}
    >
      {/* Token identity */}
      <div className="flex items-center gap-2.5">
        {token.logo_uri ? (
          <Image
            src={token.logo_uri}
            alt={token.symbol}
            width={32}
            height={32}
            className="rounded-full shrink-0 ring-1 ring-border"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="h-8 w-8 rounded-full bg-muted shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <p className="font-mono text-sm font-bold text-foreground truncate">
            {token.symbol || token.address.slice(0, 6)}
          </p>
          {token.name && (
            <p className="font-mono text-[9px] text-muted-foreground truncate">
              {token.name}
            </p>
          )}
        </div>
      </div>

      {/* Signal badge */}
      <SignalBadge signal={token.signal} />

      {/* Buy / Sell volume breakdown (only when data is available) */}
      {hasVolume && (
        <div className="grid grid-cols-2 gap-1.5 font-mono text-[9px]">
          <div className="rounded bg-buy/5 border border-buy/10 px-1.5 py-1 text-center">
            <div className="text-buy/60 mb-0.5">BUY</div>
            <div className="text-foreground font-semibold">{fmtUsd(token.buy_usd)}</div>
          </div>
          <div className="rounded bg-sell/5 border border-sell/10 px-1.5 py-1 text-center">
            <div className="text-sell/60 mb-0.5">SELL</div>
            <div className="text-foreground font-semibold">{fmtUsd(token.sell_usd)}</div>
          </div>
        </div>
      )}
    </Link>
  );
}

function FilterPill({
  label,
  active,
  color,
  onClick,
}: {
  label: string;
  active: boolean;
  color: "cyan" | "buy" | "sell" | "neutral";
  onClick: () => void;
}) {
  const activeCls =
    color === "buy"
      ? "bg-buy/15 border-buy/40 text-buy"
      : color === "sell"
      ? "bg-sell/15 border-sell/40 text-sell"
      : color === "neutral"
      ? "bg-muted/30 border-border/50 text-muted-foreground"
      : "bg-cyan/10 border-cyan/40 text-cyan";

  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 font-mono text-[10px] font-semibold uppercase tracking-wider transition-colors ${
        active
          ? activeCls
          : "bg-transparent border-border/40 text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}

// ──────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────

export default function SmartMoneyPage() {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterValue>("ALL");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/smart-money/heatmap?limit=20`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const tokens = data?.tokens ?? [];
  const buyCount = tokens.filter((t) => t.signal === "BUY").length;
  const sellCount = tokens.filter((t) => t.signal === "SELL").length;
  const neutralCount = tokens.filter((t) => t.signal === "NEUTRAL").length;

  const filtered =
    filter === "ALL" ? tokens : tokens.filter((t) => t.signal === filter);

  const generatedAt = data?.generated_at
    ? new Date(data.generated_at * 1000).toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <NavBar />

      <main className="mx-auto max-w-6xl px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Zap size={16} className="text-cyan" />
              <h1 className="font-mono text-xl font-bold tracking-tight text-foreground">
                Smart Money
              </h1>
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              Tokens smart money wallets are accumulating · Green = buying · Red = selling · Click any token for analysis
            </p>
          </div>

          <div className="flex items-center gap-3">
            {generatedAt && (
              <span className="font-mono text-[10px] text-muted-foreground">
                Updated {generatedAt}
              </span>
            )}
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-md border border-border/60 bg-card px-3 py-1.5 font-mono text-xs text-muted-foreground hover:text-foreground hover:border-border transition-colors disabled:opacity-40"
            >
              <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
          </div>
        </div>

        {/* Filter pills */}
        {!loading && tokens.length > 0 && (
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <FilterPill
              label={`All (${tokens.length})`}
              active={filter === "ALL"}
              color="cyan"
              onClick={() => setFilter("ALL")}
            />
            <FilterPill
              label={`Accumulating (${buyCount})`}
              active={filter === "BUY"}
              color="buy"
              onClick={() => setFilter("BUY")}
            />
            <FilterPill
              label={`Distributing (${sellCount})`}
              active={filter === "SELL"}
              color="sell"
              onClick={() => setFilter("SELL")}
            />
            <FilterPill
              label={`Neutral (${neutralCount})`}
              active={filter === "NEUTRAL"}
              color="neutral"
              onClick={() => setFilter("NEUTRAL")}
            />
          </div>
        )}

        {/* Content */}
        {loading && !data ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
            <p className="font-mono text-xs text-muted-foreground">
              Loading smart money signals…
            </p>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-sell/30 bg-sell/5 p-8 text-center">
            <p className="font-mono text-sm text-sell">Failed to load: {error}</p>
            <button
              onClick={fetchData}
              className="mt-4 rounded-md border border-border/60 bg-card px-4 py-2 font-mono text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Retry
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-border bg-muted/10 p-8 text-center">
            <p className="font-mono text-sm text-muted-foreground">No tokens found.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {filtered.map((token) => (
              <TokenCard key={token.address} token={token} />
            ))}
          </div>
        )}

        <p className="mt-6 font-mono text-[9px] text-muted-foreground/60 text-center">
          Data powered by Birdeye Smart Money · Cached 15 min · Click any token for full analysis
        </p>
      </main>
    </div>
  );
}
