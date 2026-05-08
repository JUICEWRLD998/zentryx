"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, BarChart2, Clock, Droplets, ExternalLink,
  Radio, RefreshCw, ShieldAlert, Zap,
} from "lucide-react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────

type NewListing = {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  price: number;
  volume_24h_usd: number;
  market_cap: number;
  liquidity: number;
  source: string;
  age_hours: number;
  freezeable: boolean;
  mutable_metadata: boolean;
  transfer_fee: boolean;
  top10_holder_pct: number;
  risk_level: "SAFE" | "RISKY" | "DANGER" | "UNKNOWN";
};

// ─── Scoring ──────────────────────────────────────────────────────────────────

interface TokenScore {
  risk: number;       // 0–100, higher = safer
  opportunity: number; // 0–100
  verdict: "BUY" | "WATCH" | "AVOID";
  verdictReason: string;
  signals: string[];
  confidence: number;
}

function scoreToken(token: NewListing): TokenScore {
  const signals: string[] = [];
  let risk = 75; // start optimistic, subtract for flags

  // Risk flags
  if (token.freezeable)         { risk -= 30; signals.push("Freeze authority active"); }
  if (token.transfer_fee)       { risk -= 25; signals.push("Transfer fee enabled"); }
  if (token.mutable_metadata)   { risk -= 10; signals.push("Mutable metadata"); }
  if (token.top10_holder_pct > 80) { risk -= 15; signals.push(`Top-10 hold ${token.top10_holder_pct.toFixed(0)}%`); }
  if (token.risk_level === "DANGER") risk = Math.min(risk, 25);
  if (token.risk_level === "RISKY")  risk = Math.min(risk, 55);

  // Opportunity
  let opportunity = 30;
  const liq = token.liquidity;
  if (liq >= 500_000) { opportunity += 35; signals.push("Strong liquidity"); }
  else if (liq >= 100_000) { opportunity += 20; }
  else if (liq >= 20_000)  { opportunity += 10; }
  else { opportunity -= 10; signals.push("Low liquidity"); }

  if (token.volume_24h_usd >= 100_000) { opportunity += 20; signals.push("High volume"); }
  else if (token.volume_24h_usd >= 10_000) { opportunity += 10; }

  const age = token.age_hours;
  if (age < 0.5) { opportunity += 10; signals.push("Brand new listing"); }
  else if (age < 2) { opportunity += 5; }

  risk        = Math.max(0, Math.min(100, Math.round(risk)));
  opportunity = Math.max(0, Math.min(100, Math.round(opportunity)));

  const flagCount = (token.freezeable ? 1 : 0) + (token.transfer_fee ? 1 : 0) + (token.mutable_metadata ? 1 : 0);
  const confidence = flagCount > 0 ? 0.9 : 0.6; // lower confidence if no security data checked

  let verdict: "BUY" | "WATCH" | "AVOID";
  let verdictReason: string;
  if (risk < 30 || token.risk_level === "DANGER") {
    verdict = "AVOID";
    verdictReason = "High-risk security flags detected. Avoid until resolved.";
  } else if (risk >= 65 && opportunity >= 50) {
    verdict = "BUY";
    verdictReason = "Clean security profile with meaningful liquidity. Worth watching closely.";
  } else {
    verdict = "WATCH";
    verdictReason = "Moderate risk or opportunity. Monitor before committing capital.";
  }

  return { risk, opportunity, verdict, verdictReason, signals, confidence };
}

// ─── Formatting helpers ───────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (!n || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000)     return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)         return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}

function fmtAge(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`;
  return `${Math.floor(hours / 24)}d`;
}

function fmtAddr(addr: string, chars = 4): string {
  if (!addr || addr.length < chars * 2 + 3) return addr;
  return `${addr.slice(0, chars)}…${addr.slice(-chars)}`;
}

function fmtSource(source: string): string {
  if (!source) return "DEX";
  return source.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    .replace("Amm", "AMM").replace("Damm", "DAMM").replace("Clamm", "CLMM");
}

// ─── Token logo ───────────────────────────────────────────────────────────────

function TokenLogo({ uri, symbol }: { uri: string; symbol: string }) {
  return (
    <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-full bg-muted">
      <span className="absolute inset-0 flex items-center justify-center font-mono text-[9px] font-bold text-muted-foreground">
        {symbol.slice(0, 2).toUpperCase()}
      </span>
      {uri && <Image src={uri} alt={symbol} fill unoptimized className="rounded-full object-cover" />}
    </div>
  );
}

// ─── Score meter ──────────────────────────────────────────────────────────────

function ScoreMeter({ score, label }: { score: number; label: string }) {
  const color = score >= 75 ? "bg-buy" : score >= 50 ? "bg-yellow-400" : "bg-sell";
  const text  = score >= 75 ? "text-buy" : score >= 50 ? "text-yellow-400" : "text-sell";
  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-center justify-between">
        <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{label}</p>
        <span className={`font-mono text-xs font-bold tabular-nums ${text}`}>{score}</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full transition-[width] duration-700 ${color}`} style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}

// ─── Token card ───────────────────────────────────────────────────────────────

function TokenCard({ token, rank }: { token: NewListing; rank: number }) {
  const score  = scoreToken(token);
  const isNew  = token.age_hours < 0.5;

  const borderGlow =
    score.verdict === "BUY"   ? "border-buy/30 hover:border-buy/60 hover:shadow-lg hover:shadow-buy/10" :
    score.verdict === "AVOID" ? "border-sell/30 hover:border-sell/60 hover:shadow-lg hover:shadow-sell/10" :
                                "border-border hover:border-border/80";

  const verdictBg =
    score.verdict === "BUY"   ? "bg-buy/10 text-buy ring-buy/25" :
    score.verdict === "AVOID" ? "bg-sell/10 text-sell ring-sell/25" :
                                "bg-yellow-400/10 text-yellow-400 ring-yellow-400/25";

  return (
    <div className={`relative flex flex-col gap-4 rounded-xl border bg-card p-4 sm:p-5 transition-all duration-200 hover:-translate-y-0.5 ${borderGlow}`}>
      {/* Rank */}
      <span className="absolute left-3 top-3 font-mono text-[10px] text-muted-foreground">#{rank}</span>

      {/* Header */}
      <div className="flex items-start gap-3 pl-5">
        <TokenLogo uri={token.logo_uri} symbol={token.symbol} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Link
              href={`/token/${token.address}`}
              className="truncate font-semibold text-foreground transition-colors hover:text-cyan"
            >
              {token.name || token.symbol}
            </Link>
            {isNew && (
              <span className="inline-flex items-center rounded-full bg-cyan/20 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-cyan ring-1 ring-cyan/35">
                NEW
              </span>
            )}
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
        {/* Verdict */}
        <span className={`shrink-0 inline-flex items-center rounded-full px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wider ring-1 ${verdictBg}`}>
          {score.verdict}
        </span>
      </div>

      {/* Liquidity · Source · Age */}
      <div className="grid grid-cols-3 gap-2 border-t border-border/50 pt-3">
        <div>
          <div className="mb-1 flex items-center gap-1">
            <Droplets className="h-2.5 w-2.5 text-cyan" />
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Liquidity</p>
          </div>
          <p className="font-mono text-sm font-bold text-foreground">${fmtNum(token.liquidity)}</p>
        </div>
        <div>
          <div className="mb-1 flex items-center gap-1">
            <Radio className="h-2.5 w-2.5 text-cyan" />
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Listed on</p>
          </div>
          <p className="truncate font-mono text-xs font-medium text-foreground">{fmtSource(token.source)}</p>
        </div>
        <div className="text-right">
          <div className="mb-1 flex items-center justify-end gap-1">
            <Clock className="h-2.5 w-2.5 text-muted-foreground" />
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Age</p>
          </div>
          <p className="font-mono text-sm text-foreground">{fmtAge(token.age_hours)}</p>
        </div>
      </div>

      {/* Score meters */}
      <div className="space-y-2.5">
        <ScoreMeter score={score.risk}        label="Risk Score (higher = safer)" />
        <ScoreMeter score={score.opportunity} label="Opportunity" />
      </div>

      {/* Security flags */}
      {(token.freezeable || token.transfer_fee || token.mutable_metadata) && (
        <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-3">
          {token.freezeable       && <Flag label="FREEZEABLE" />}
          {token.transfer_fee     && <Flag label="TRANSFER FEE" />}
          {token.mutable_metadata && <Flag label="MUTABLE META" />}
        </div>
      )}

      {/* Signal count + confidence */}
      <div className="flex items-center justify-between border-t border-border/50 pt-3">
        <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <Zap className="h-3 w-3 text-cyan" />
          <span>{score.signals.length} signals</span>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <BarChart2 className="h-3 w-3" />
          <span>Confidence: <span className={score.confidence >= 0.75 ? "text-buy" : score.confidence >= 0.5 ? "text-yellow-400" : "text-sell"}>{Math.round(score.confidence * 100)}%</span></span>
        </div>
      </div>

      {/* Verdict reason */}
      <p className="border-t border-border/50 pt-3 font-mono text-[11px] leading-snug text-muted-foreground">
        {score.verdictReason}
      </p>
    </div>
  );
}

function Flag({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-sell/25 bg-sell/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-wider text-sell">
      <AlertTriangle className="h-2 w-2" />
      {label}
    </span>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NewListingsPage() {
  const [tokens, setTokens]         = useState<NewListing[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/new-listings`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as NewListing[];
      // Sort best-first by risk (highest risk score = safer)
      const sorted = [...(Array.isArray(raw) ? raw : [])].sort((a, b) => {
        const sa = scoreToken(a);
        const sb = scoreToken(b);
        return (sb.risk + sb.opportunity) - (sa.risk + sa.opportunity);
      });
      setTokens(sorted);
      setLastRefresh(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 60_000);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="new-listings" />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 space-y-6">

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan/10">
              <ShieldAlert className="h-5 w-5 text-cyan" />
            </div>
            <div>
              <h1 className="font-mono text-xl font-bold text-foreground">Token Radar</h1>
              <p className="font-mono text-xs text-muted-foreground">New listings scored by risk, opportunity &amp; momentum</p>
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
              <span className="hidden font-mono text-xs text-muted-foreground sm:inline">· 60s refresh</span>
            </div>
            <button
              onClick={fetchData}
              disabled={loading}
              suppressHydrationWarning
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
            <AlertTriangle className="h-4 w-4 shrink-0 text-sell" />
            <span>Failed to load new listings: {error}</span>
          </div>
        )}

        {/* ── Skeleton ─────────────────────────────────────────────────── */}
        {loading && tokens.length === 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-80 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
        )}

        {/* ── Empty state ───────────────────────────────────────────────── */}
        {!loading && tokens.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border bg-card p-10 text-center">
            <ShieldAlert className="h-8 w-8 text-muted-foreground" />
            <p className="font-mono text-sm text-muted-foreground">No new listings found. The radar will refresh automatically.</p>
          </div>
        )}

        {/* ── Card grid ─────────────────────────────────────────────────── */}
        {tokens.length > 0 && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {tokens.map((t, idx) => (
              <TokenCard key={t.address} token={t} rank={idx + 1} />
            ))}
          </div>
        )}

      </main>
    </div>
  );
}
