"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { NavBar } from "@/components/navbar";
import { RefreshCw, Zap, ExternalLink, Star } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────

type Signal = "BUY" | "SELL" | "NEUTRAL";
type FilterValue = "ALL" | Signal | "WHALE_OVERLAP";

interface WhaleTrade {
  wallet_label: string;
  side: "BUY" | "SELL" | "UNKNOWN";
  usd_value: number;
}

interface SmartMoneyToken {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  signal: Signal;
  buy_usd: number;
  sell_usd: number;
  net_usd: number;
  smart_money_count: number;
  tracked_whale_trades: WhaleTrade[];
}

interface HeatmapData {
  tokens: SmartMoneyToken[];
  generated_at: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(n: number): string {
  if (!isFinite(n) || n === 0) return "$0";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtAddr(addr: string, chars = 4): string {
  if (!addr || addr.length < chars * 2 + 3) return addr;
  return `${addr.slice(0, chars)}…${addr.slice(-chars)}`;
}

function computeConfidence(token: SmartMoneyToken): number {
  // Primary signal: smart_money_count normalized against 200 (≥200 wallets = max 60 pts)
  // Whale boost: +20 per tracked whale trade (max 40 pts)
  const smScore = Math.min(60, Math.round(((token.smart_money_count ?? 0) / 200) * 60));
  const whaleBoost = Math.min(40, token.tracked_whale_trades.length * 20);
  return Math.min(100, smScore + whaleBoost);
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function TokenLogo({ uri, symbol, cls = "h-10 w-10" }: { uri: string; symbol: string; cls?: string }) {
  return (
    <div className={`relative ${cls} shrink-0 overflow-hidden rounded-full bg-muted`}>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[9px] font-bold text-muted-foreground">
        {symbol.slice(0, 2).toUpperCase()}
      </span>
      {uri && (
        <Image
          src={uri}
          alt={symbol}
          fill
          unoptimized
          className="rounded-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      )}
    </div>
  );
}

function TokenCard({ token, rank }: { token: SmartMoneyToken; rank: number }) {
  const hasWhales = token.tracked_whale_trades.length > 0;
  const confidence = computeConfidence(token);
  const netFlow = token.buy_usd - token.sell_usd;

  // Mirror trending's glow/border logic keyed on signal + whale presence
  const glow = hasWhales
    ? "border-yellow-400/40 hover:border-yellow-400/70 hover:shadow-lg hover:shadow-yellow-400/10"
    : token.signal === "BUY"
    ? "border-buy/40 hover:border-buy/70 hover:shadow-lg hover:shadow-buy/10"
    : token.signal === "SELL"
    ? "border-sell/30 hover:border-sell/60 hover:shadow-lg hover:shadow-sell/10"
    : "border-border/50 hover:border-border hover:shadow-lg hover:shadow-muted/10";

  const barColor = hasWhales
    ? "bg-yellow-400"
    : confidence >= 70
    ? token.signal === "SELL" ? "bg-sell" : "bg-buy"
    : confidence >= 40
    ? "bg-yellow-400"
    : "bg-muted-foreground/40";

  const confidenceColor = hasWhales
    ? "text-yellow-400"
    : confidence >= 70
    ? token.signal === "SELL" ? "text-sell" : "text-buy"
    : confidence >= 40
    ? "text-yellow-400"
    : "text-muted-foreground";

  const signalLabel =
    token.signal === "BUY" ? "ACCUMULATING" :
    token.signal === "SELL" ? "DISTRIBUTING" : "NEUTRAL";

  const signalCls =
    token.signal === "BUY"
      ? "bg-buy/20 text-buy ring-1 ring-buy/35"
      : token.signal === "SELL"
      ? "bg-sell/20 text-sell ring-1 ring-sell/35"
      : "bg-muted/40 text-muted-foreground ring-1 ring-border/40";

  return (
    <div className={`relative flex flex-col gap-4 rounded-xl border bg-card p-5 transition-all duration-200 ${glow}`}>

      {/* Rank */}
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <span className="font-mono text-[10px] text-muted-foreground">#{rank}</span>
      </div>

      {/* Header — logo + name + signal badge */}
      <div className="flex items-start gap-3">
        <TokenLogo uri={token.logo_uri} symbol={token.symbol || token.address.slice(0, 2)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Link
              href={`/token/${token.address}`}
              className="font-semibold text-foreground transition-colors hover:text-cyan truncate"
            >
              {token.name || token.symbol}
            </Link>
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${signalCls}`}>
              {signalLabel}
            </span>
            {hasWhales && (
              <Star size={10} className="shrink-0 text-yellow-400 fill-yellow-400/60" />
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{token.symbol}</span>
            <span className="text-xs text-muted-foreground">·</span>
            <span className="font-mono text-xs text-muted-foreground">{fmtAddr(token.address)}</span>
            <Link
              href={`https://solscan.io/token/${token.address}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground transition-colors hover:text-cyan"
            >
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* SM Wallets · Buy Vol · Sell Vol stats row */}
      <div className="flex items-end justify-between border-t border-border/50 pt-3">
        <div>
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">SM Wallets</p>
          <p className="font-mono text-sm font-bold text-cyan">
            {token.smart_money_count > 0 ? token.smart_money_count : "—"}
          </p>
        </div>
        <div className="text-center">
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Buy Vol</p>
          <p className="font-mono text-sm font-bold text-buy">
            {token.buy_usd > 0 ? fmtUsd(token.buy_usd) : "—"}
          </p>
        </div>
        <div className="text-right">
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Sell Vol</p>
          <p className="font-mono text-sm font-bold text-sell">
            {token.sell_usd > 0 ? fmtUsd(token.sell_usd) : "—"}
          </p>
        </div>
      </div>

      {/* Whale pills */}
      {hasWhales && (
        <div className="flex flex-wrap gap-1.5">
          {token.tracked_whale_trades.slice(0, 3).map((t, i) => (
            <span
              key={i}
              className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[9px] font-bold tracking-wider ${
                t.side === "BUY"
                  ? "border-buy/20 bg-buy/10 text-buy"
                  : t.side === "SELL"
                  ? "border-sell/20 bg-sell/10 text-sell"
                  : "border-border/30 bg-muted/30 text-muted-foreground"
              }`}
            >
              <Star className="h-2 w-2 fill-current" />
              {t.wallet_label} · {fmtUsd(t.usd_value)}
            </span>
          ))}
          {token.tracked_whale_trades.length > 3 && (
            <span className="inline-flex items-center rounded border border-border/30 bg-muted/20 px-2 py-0.5 font-mono text-[9px] text-muted-foreground">
              +{token.tracked_whale_trades.length - 3} more
            </span>
          )}
        </div>
      )}

      {/* Signal Confidence meter — mirrors Breakout Intensity */}
      <div className="border-t border-border/50 pt-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Signal Confidence
          </span>
          <span className={`font-mono text-xs font-bold ${confidenceColor}`}>
            {confidence}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full transition-[width] duration-700 ${barColor}`}
            style={{ width: `${confidence}%` }}
          />
        </div>
      </div>
    </div>
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
  color: "cyan" | "buy" | "sell" | "neutral" | "whale";
  onClick: () => void;
}) {
  const activeCls =
    color === "buy"
      ? "bg-buy/15 border-buy/40 text-buy"
      : color === "sell"
      ? "bg-sell/15 border-sell/40 text-sell"
      : color === "neutral"
      ? "bg-muted/30 border-border/50 text-muted-foreground"
      : color === "whale"
      ? "bg-yellow-400/15 border-yellow-400/40 text-yellow-400"
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
  const whaleOverlapCount = tokens.filter((t) => t.tracked_whale_trades.length > 0).length;

  const filtered =
    filter === "ALL"
      ? tokens
      : filter === "WHALE_OVERLAP"
      ? tokens.filter((t) => t.tracked_whale_trades.length > 0)
      : tokens.filter((t) => t.signal === filter);

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
              Tokens smart money wallets are actively trading · ★ = our tracked whales also in this position
            </p>
          </div>

          <div className="flex items-center gap-3">
            {generatedAt && (
              <span className="font-mono text-[10px] text-muted-foreground">
                Fetched {generatedAt} · refreshes every 15 min
              </span>
            )}
            <button
              onClick={fetchData}
              disabled={loading}
              suppressHydrationWarning
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
            {whaleOverlapCount > 0 && (
              <FilterPill
                label={`★ Whale Overlap (${whaleOverlapCount})`}
                active={filter === "WHALE_OVERLAP"}
                color="whale"
                onClick={() => setFilter("WHALE_OVERLAP")}
              />
            )}
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
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {filtered.map((token, idx) => (
              <TokenCard key={token.address} token={token} rank={idx + 1} />
            ))}
          </div>
        )}


      </main>
    </div>
  );
}
