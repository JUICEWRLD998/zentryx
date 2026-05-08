"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Activity, BarChart2, ExternalLink, RefreshCw, TrendingUp, Zap } from "lucide-react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────

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

// ─── Breakout detection ───────────────────────────────────────────────────────

const THRESH = {
  VOLUME_SURGE:    100,
  VOLUME_NOTABLE:   50,
  PRICE_SPIKE:      15,
  PRICE_EXTREME:    60,
  RANK_TOP:          5,
  RANK_VOL_CONFIRM: 50,
} as const;

type SignalKey = "VOLUME SURGE" | "PRICE SPIKE" | "RANK MOVER";

interface Breakout {
  isBreakout: boolean;
  score: number;
  signals: SignalKey[];
}

function detect(token: TrendingToken): Breakout {
  const vol = isFinite(token.volume_change_24h) ? token.volume_change_24h : 0;
  const prc = isFinite(token.price_change_24h)  ? token.price_change_24h  : 0;

  const volumeBreakout = vol > THRESH.VOLUME_SURGE;
  const priceBreakout  = prc > THRESH.PRICE_SPIKE;
  const rankBreakout   = token.rank <= THRESH.RANK_TOP && vol > THRESH.RANK_VOL_CONFIRM;
  const isBreakout     = volumeBreakout || priceBreakout || rankBreakout;

  const signals: SignalKey[] = [];
  let score = 0;

  if (volumeBreakout) {
    score += 20 + Math.min(15, (vol - THRESH.VOLUME_SURGE) / 27);
    signals.push("VOLUME SURGE");
  } else if (vol > THRESH.VOLUME_NOTABLE) {
    score += 8;
  }
  if (prc > THRESH.PRICE_EXTREME) {
    score += 35;
    signals.push("PRICE SPIKE");
  } else if (priceBreakout) {
    score += Math.min(25, (prc - THRESH.PRICE_SPIKE) * 0.7 + 10);
    signals.push("PRICE SPIKE");
  } else if (prc > 5) {
    score += 5;
  }
  if (rankBreakout) { score += 20; signals.push("RANK MOVER"); }
  if (token.rank === 1) score += 10;

  return { isBreakout, score: Math.min(100, Math.round(score)), signals };
}

// ─── Formatting helpers ───────────────────────────────────────────────────────

function fmtPrice(n: number): string {
  if (!n || !isFinite(n)) return "$0";
  if (n < 0.000001) return `$${n.toExponential(2)}`;
  if (n < 0.01)     return `$${n.toFixed(6)}`;
  if (n < 1)        return `$${n.toFixed(4)}`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n);
}

function fmtNum(n: number): string {
  if (!n || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)     return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)         return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}

function fmtPct(n: number): string {
  if (!isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function fmtAddr(addr: string, chars = 4): string {
  if (!addr || addr.length < chars * 2 + 3) return addr;
  return `${addr.slice(0, chars)}…${addr.slice(-chars)}`;
}

function pctColor(n: number): string {
  if (n > 0) return "text-buy";
  if (n < 0) return "text-sell";
  return "text-muted-foreground";
}

function scoreColor(score: number): string {
  if (score >= 75) return "text-buy";
  if (score >= 50) return "text-yellow-400";
  return "text-sell";
}

// ─── Token logo ───────────────────────────────────────────────────────────────

function TokenLogo({ uri, symbol, cls = "h-10 w-10" }: { uri: string; symbol: string; cls?: string }) {
  return (
    <div className={`relative ${cls} shrink-0 overflow-hidden rounded-full bg-muted`}>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[9px] font-bold text-muted-foreground">
        {symbol.slice(0, 2).toUpperCase()}
      </span>
      {uri && <Image src={uri} alt={symbol} fill unoptimized className="rounded-full object-cover" />}
    </div>
  );
}

// ─── Breakout card ────────────────────────────────────────────────────────────

function BreakoutCard({ token }: { token: TrendingToken }) {
  const b = detect(token);

  const glow =
    b.score >= 80 ? "border-buy/40 hover:border-buy/70 hover:shadow-lg hover:shadow-buy/10" :
    b.score >= 55 ? "border-yellow-400/40 hover:border-yellow-400/70 hover:shadow-lg hover:shadow-yellow-400/10" :
                    "border-cyan/30 hover:border-cyan/60 hover:shadow-lg hover:shadow-cyan/10";

  const barColor = b.score >= 80 ? "bg-buy" : b.score >= 55 ? "bg-yellow-400" : "bg-cyan";

  return (
    <div className={`relative flex flex-col gap-4 rounded-xl border bg-card p-5 transition-all duration-200 ${glow}`}>
      {/* Rank + link */}
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <span className="font-mono text-[10px] text-muted-foreground">#{token.rank}</span>
      </div>

      {/* Header */}
      <div className="flex items-start gap-3">
        <TokenLogo uri={token.logo_uri} symbol={token.symbol} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Link
              href={`/token/${token.address}`}
              className="font-semibold text-foreground transition-colors hover:text-cyan truncate"
            >
              {token.name || token.symbol}
            </Link>
            <span className="inline-flex items-center rounded-full bg-cyan/20 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-cyan ring-1 ring-cyan/35">
              BREAKOUT
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">{token.symbol}</span>
            <span className="text-xs text-muted-foreground">·</span>
            <span className="font-mono text-xs text-muted-foreground">{fmtAddr(token.address)}</span>
            <Link
              href={`https://solscan.io/token/${token.address}`}
              target="_blank" rel="noopener noreferrer"
              className="text-muted-foreground transition-colors hover:text-cyan"
            >
              <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* Price · 24h · Volume */}
      <div className="flex items-end justify-between border-t border-border/50 pt-3">
        <div>
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Price</p>
          <p className="font-mono text-sm font-bold text-foreground">{fmtPrice(token.price)}</p>
        </div>
        <div className="text-right">
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">24h</p>
          <p className={`font-mono text-sm font-bold ${pctColor(token.price_change_24h)}`}>
            {fmtPct(token.price_change_24h)}
          </p>
        </div>
        <div className="text-right">
          <p className="mb-0.5 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Volume</p>
          <p className="font-mono text-sm text-muted-foreground">${fmtNum(token.volume_24h_usd)}</p>
        </div>
      </div>

      {/* Signal pills */}
      {b.signals.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {b.signals.map((sig) => (
            <span
              key={sig}
              className="inline-flex items-center gap-1 rounded border border-cyan/20 bg-cyan/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-wider text-cyan"
            >
              <Zap className="h-2 w-2" />
              {sig}
            </span>
          ))}
        </div>
      )}

      {/* Intensity meter */}
      <div className="border-t border-border/50 pt-3">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Breakout Intensity</span>
          <span className={`font-mono text-xs font-bold ${scoreColor(b.score)}`}>{b.score}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div className={`h-full rounded-full transition-[width] duration-700 ${barColor}`} style={{ width: `${b.score}%` }} />
        </div>
      </div>

    </div>
  );
}

// ─── Mobile row ───────────────────────────────────────────────────────────────

function MobileRow({ token }: { token: TrendingToken }) {
  const b = detect(token);
  return (
    <Link
      href={`/token/${token.address}`}
      className={`flex items-center gap-3 border-b border-border/40 px-4 py-3 transition-colors ${b.isBreakout ? "hover:bg-cyan/5" : "hover:bg-muted/30"}`}
    >
      <span className={`w-5 shrink-0 font-mono text-xs font-bold ${token.rank <= 3 ? "text-cyan" : "text-muted-foreground"}`}>
        {token.rank}
      </span>
      <TokenLogo uri={token.logo_uri} symbol={token.symbol} cls="h-8 w-8" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-semibold text-foreground">{token.symbol}</span>
          {b.isBreakout && (
            <span className="rounded-full bg-cyan/20 px-1.5 py-0.5 font-mono text-[9px] font-bold text-cyan ring-1 ring-cyan/35">BREAKOUT</span>
          )}
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">{fmtAddr(token.address)}</span>
      </div>
      <div className="text-right">
        <p className="font-mono text-sm text-foreground">{fmtPrice(token.price)}</p>
        <p className={`font-mono text-[10px] font-bold ${pctColor(token.price_change_24h)}`}>
          {fmtPct(token.price_change_24h)}
        </p>
      </div>
    </Link>
  );
}

// ─── Desktop table row ────────────────────────────────────────────────────────

function TableRow({ token }: { token: TrendingToken }) {
  const b = detect(token);
  return (
    <tr className={`group border-b border-border/40 transition-colors ${b.isBreakout ? "hover:bg-cyan/5" : "hover:bg-muted/20"}`}>
      <td className="px-4 py-3">
        <span className={`font-mono text-sm font-bold ${token.rank <= 3 ? "text-cyan" : "text-muted-foreground"}`}>{token.rank}</span>
      </td>
      <td className="px-4 py-3">
        <Link href={`/token/${token.address}`} className="flex items-center gap-2.5">
          <TokenLogo uri={token.logo_uri} symbol={token.symbol} cls="h-7 w-7" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground transition-colors group-hover:text-cyan">{token.symbol}</p>
            <p className="font-mono text-[10px] text-muted-foreground">{fmtAddr(token.address)}</p>
          </div>
          {b.isBreakout && (
            <span className="rounded-full bg-cyan/20 px-1.5 py-0.5 font-mono text-[9px] font-bold text-cyan ring-1 ring-cyan/35">BREAKOUT</span>
          )}
        </Link>
      </td>
      <td className="px-4 py-3 text-right">
        <span className="font-mono text-sm text-foreground">{fmtPrice(token.price)}</span>
      </td>
      <td className="px-4 py-3 text-right">
        <span className={`font-mono text-sm font-bold ${pctColor(token.price_change_24h)}`}>{fmtPct(token.price_change_24h)}</span>
      </td>
      <td className="px-4 py-3 text-right">
        <div>
          <p className="font-mono text-sm text-foreground">${fmtNum(token.volume_24h_usd)}</p>
          {isFinite(token.volume_change_24h) && token.volume_change_24h !== 0 && (
            <p className={`font-mono text-[10px] ${pctColor(token.volume_change_24h)}`}>
              {token.volume_change_24h > 0 ? "+" : ""}{token.volume_change_24h.toFixed(0)}% vol
            </p>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <span className="font-mono text-sm text-muted-foreground">{token.market_cap > 0 ? `$${fmtNum(token.market_cap)}` : "—"}</span>
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {b.signals.map((sig) => (
            <span key={sig} className="inline-flex items-center gap-0.5 rounded border border-cyan/20 bg-cyan/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-cyan">
              <Zap className="h-2 w-2" />
              {sig}
            </span>
          ))}
          {!b.isBreakout && <span className="font-mono text-[10px] text-muted-foreground">—</span>}
        </div>
      </td>
    </tr>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TrendingPage() {
  const [tokens, setTokens] = useState<TrendingToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
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
    fetchData();
    const id = setInterval(fetchData, 30_000);
    return () => clearInterval(id);
  }, [fetchData]);

  const breakouts = tokens.filter((t) => detect(t).isBreakout);
  const ranked    = [...tokens].sort((a, b) => a.rank - b.rank);

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="trending" />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 space-y-8">

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan/10">
              <Activity className="h-5 w-5 text-cyan" />
            </div>
            <div>
              <h1 className="font-mono text-xl font-bold text-foreground">Trending Breakouts</h1>
              <p className="font-mono text-xs text-muted-foreground">Volume surge · Price spike · Smart money signal</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastRefresh && (
              <span className="font-mono text-xs text-muted-foreground" suppressHydrationWarning>
                {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-buy" />
              <span className="font-mono text-xs font-medium text-muted-foreground">LIVE</span>
              <span className="hidden font-mono text-xs text-muted-foreground sm:inline">· 30s refresh</span>
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 font-mono text-xs text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground disabled:opacity-50"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              REFRESH
            </button>
          </div>
        </div>

        {/* ── Error ────────────────────────────────────────────────────── */}
        {error && (
          <div className="flex items-center gap-3 rounded-lg border border-sell/20 bg-sell/5 px-5 py-4 font-mono text-xs text-muted-foreground">
            <Activity className="h-4 w-4 shrink-0 text-sell" />
            <span>Failed to load trending tokens: {error}</span>
          </div>
        )}

        {/* ── Loading skeleton ─────────────────────────────────────────── */}
        {loading && tokens.length === 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-56 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
        )}

        {/* ── Breakout highlights ──────────────────────────────────────── */}
        {!loading && breakouts.length > 0 && (
          <section>
            <div className="mb-4 flex items-center gap-2">
              <Zap className="h-4 w-4 text-cyan" />
              <h2 className="font-mono text-base font-semibold text-foreground">Active Breakouts</h2>
              <span className="rounded-full bg-cyan/20 px-2.5 py-1 font-mono text-[10px] font-bold text-cyan ring-1 ring-cyan/35">
                {breakouts.length}
              </span>
              <span className="ml-auto hidden font-mono text-xs text-muted-foreground sm:inline">
                Volume surge · Price spike · Rank movement
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {breakouts.map((t) => <BreakoutCard key={t.address} token={t} />)}
            </div>
          </section>
        )}

        {!loading && breakouts.length === 0 && tokens.length > 0 && (
          <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-5 py-4 font-mono text-xs text-muted-foreground">
            <BarChart2 className="h-4 w-4 shrink-0" />
            <span>No active breakout signals right now — check back in 30 seconds.</span>
          </div>
        )}

        {/* ── Full rankings ─────────────────────────────────────────────── */}
        {ranked.length > 0 && (
          <section>
            <div className="mb-4 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
              <h2 className="font-mono text-base font-semibold text-foreground">Full Rankings</h2>
              <span className="font-mono text-xs text-muted-foreground">Top {ranked.length} by volume</span>
            </div>

            <div className="overflow-hidden rounded-xl border border-border bg-card">
              {/* Mobile */}
              <div className="md:hidden">
                {ranked.map((t) => <MobileRow key={t.address} token={t} />)}
              </div>

              {/* Desktop */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      {["#", "Token", "Price", "24h %", "Volume", "Mkt Cap", "Signals"].map((col, i) => (
                        <th
                          key={col}
                          className={`px-4 py-3 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground ${i <= 1 || i === 6 ? "text-left" : "text-right"}`}
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((t) => <TableRow key={t.address} token={t} />)}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

      </main>
    </div>
  );
}
