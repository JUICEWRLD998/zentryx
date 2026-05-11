"use client";

import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, ArrowLeft, ArrowRight, BarChart2, CandlestickChart, CheckCircle2,
  Droplets, ExternalLink, ShieldAlert, ShieldCheck, ShieldOff,
  Sparkles, TrendingUp, Users, XCircle, Zap, Activity, Layers,
} from "lucide-react";
import { NavBar } from "@/components/navbar";
import dynamic from "next/dynamic";

const OHLCVChart = dynamic(() => import("./_components/OHLCVChart"), {
  ssr: false,
  loading: () => (
    <div className="flex h-97.5 items-center justify-center rounded-xl border border-border bg-card">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
    </div>
  ),
});

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TokenOverview {
  address: string;
  symbol: string;
  name: string;
  logoURI: string;
  price: number;
  priceChange24hPercent: number;
  v24hUSD: number;
  v24hChangePercent: number;
  mc: number;
  realMc: number;
  liquidity: number;
  holder: number;
  supply: number;
  circulatingSupply: number;
  lastTradeUnixTime: number;
  securityScore: number | null;
  securityFlags: {
    mintable: boolean;
    freezeable: boolean;
    mutableMetadata: boolean;
    transferFee: boolean;
    top10HolderPct: number | null;
  };
}

// ─── Intelligence panel types (Phase 1 — new premium endpoints) ───────────────

interface TopTrader {
  address: string;
  label: string;
  is_tracked: boolean;
  pnl_usd: number;
  volume_usd: number;
  trade_count: number;
  win_rate: number;
}

interface HolderData {
  total_holders: number;
  top10_pct: number;
  top10: { address: string; amount: number; pct: number }[];
  distribution: unknown[];
  concentration_risk: "HIGH" | "MODERATE" | "LOW";
}

interface TradeFlowData {
  buy_count: number;
  sell_count: number;
  total_trades: number;
  buy_volume_usd: number;
  sell_volume_usd: number;
  buy_ratio: number;
  pressure: "BUY" | "SELL" | "NEUTRAL";
}

interface ExitLiquidityData {
  total_liquidity_usd: number;
  depth_1pct_usd: number;
  depth_2pct_usd: number;
  slippage_estimates: { exit_usd: number; slippage_pct: number | null }[];
  rating: "DEEP" | "ADEQUATE" | "THIN" | "CRITICAL";
}

interface PriceStatsData {
  current_price: number;
  "1h": { price_change_pct: number; high: number; low: number; volume_usd: number };
  "4h": { price_change_pct: number; high: number; low: number; volume_usd: number };
  "24h": { price_change_pct: number; high: number; low: number; volume_usd: number };
}

type IntelTab = "top-traders" | "holders" | "trade-flow" | "exit-liquidity" | "price-stats";

type Verdict = "BUY" | "WATCH" | "AVOID";
type ScoreLabel =  | "high-risk" | "low-liquidity" | "new-token" | "trending" | "breakout"
  | "whale-activity" | "low-holders" | "high-volume" | "concentrated-supply"
  | "lp-burned" | "mintable" | "freezeable" | "transfer-fee" | "mutable-metadata"
  | "volume-spike" | "price-breakout" | "low-mcap-gem" | "honeypot-risk";

interface ScoringSignal {
  label: string;
  impact: "positive" | "negative" | "neutral";
  delta: number;
  category: "risk" | "opportunity" | "momentum" | "security" | "liquidity";
}

interface TokenScore {
  overall: number; risk: number; opportunity: number; momentum: number;
  liquidity: number; security: number;
  verdict: Verdict; verdictReason: string;
  labels: ScoreLabel[]; signals: ScoringSignal[]; confidence: number;
}

// ─── Scoring engine ───────────────────────────────────────────────────────────

function clamp(v: number, min = 0, max = 100) { return Math.min(max, Math.max(min, v)); }
function normalize(v: number, lo: number, hi: number) {
  if (hi === lo) return 50;
  return clamp(((v - lo) / (hi - lo)) * 100);
}
function sig(sigs: ScoringSignal[], label: string, delta: number, category: ScoringSignal["category"]) {
  sigs.push({ label, delta, impact: delta > 0 ? "positive" : delta < 0 ? "negative" : "neutral", category });
}

function scoreToken(t: TokenOverview): TokenScore {
  const pct24h   = t.priceChange24hPercent;
  const vol24h   = t.v24hUSD;
  const volChg   = t.v24hChangePercent ?? 0;
  const mc       = t.mc;
  const liq      = t.liquidity;
  const holders  = t.holder;
  const now      = Math.floor(Date.now() / 1000);
  const ageMin   = t.lastTradeUnixTime ? Math.max(0, Math.floor((now - t.lastTradeUnixTime) / 60)) : 120;

  // ── Liquidity ──
  const liqSigs: ScoringSignal[] = []; const liqLabels: ScoreLabel[] = [];
  const logLiq = liq > 0 ? Math.log10(liq) : 0;
  let liqScore = normalize(logLiq, Math.log10(10_000), Math.log10(5_000_000));
  if (liq < 10_000)  { liqScore = clamp(liqScore - 20); liqLabels.push("low-liquidity"); sig(liqSigs, "Critically low liquidity (< $10k)", -20, "liquidity"); }
  else if (liq < 50_000) { sig(liqSigs, "Low liquidity (< $50k) — high slippage risk", -10, "liquidity"); liqLabels.push("low-liquidity"); }
  else if (liq >= 1_000_000) { sig(liqSigs, "Deep liquidity (> $1M) — healthy market depth", +10, "liquidity"); }
  if (mc > 0) {
    const ratio = liq / mc;
    if (ratio < 0.03)  { liqScore = clamp(liqScore - 15); sig(liqSigs, "Liquidity < 3% of market cap — rug-pull risk", -15, "liquidity"); }
    else if (ratio >= 0.15) { sig(liqSigs, "Strong liquidity ratio (>= 15% of mcap)", +8, "liquidity"); }
  }
  liqScore = clamp(liqScore);

  // ── Security (derived) ──
  const secSigs: ScoringSignal[] = []; const secLabels: ScoreLabel[] = [];
  let secScore = typeof t.securityScore === "number" ? t.securityScore : 60;
  if (mc > 0) {
    const r = liq / mc;
    if (r < 0.03)  { secScore -= 20; sig(secSigs, "Liquidity < 3% of market cap — potential rug risk", -20, "security"); }
    else if (r >= 0.10) { secScore += 10; sig(secSigs, "Healthy liquidity ratio (>= 10% of MC)", +10, "security"); }
  }
  if (holders < 50)   { secScore -= 20; secLabels.push("low-holders"); sig(secSigs, `Very few holders (${holders}) — high concentration risk`, -20, "security"); }
  else if (holders < 200) { secScore -= 10; secLabels.push("low-holders"); sig(secSigs, `Low holder count (${holders}) — limited distribution`, -10, "security"); }
  else if (holders >= 1000) { secScore += 8; sig(secSigs, `Strong holder base (${holders.toLocaleString()})`, +8, "security"); }
  if (t.securityFlags.freezeable) {
    secScore -= 15;
    secLabels.push("freezeable");
    sig(secSigs, "Freeze authority is enabled — centralized freeze risk", -15, "security");
  }
  if (t.securityFlags.mintable) {
    secScore -= 15;
    secLabels.push("mintable");
    sig(secSigs, "Mint authority is enabled — supply inflation risk", -15, "security");
  }
  if (t.securityFlags.transferFee) {
    secScore -= 10;
    secLabels.push("transfer-fee");
    sig(secSigs, "Transfer fee is enabled — potential trading friction", -10, "security");
  }
  if (t.securityFlags.mutableMetadata) {
    secScore -= 5;
    secLabels.push("mutable-metadata");
    sig(secSigs, "Metadata is mutable — contract metadata can change", -5, "security");
  }
  if (typeof t.securityFlags.top10HolderPct === "number" && t.securityFlags.top10HolderPct > 80) {
    secScore -= 10;
    secLabels.push("concentrated-supply");
    sig(secSigs, `Top 10 holders own ${t.securityFlags.top10HolderPct.toFixed(1)}% — high concentration`, -10, "security");
  }
  secScore = clamp(secScore);

  // ── Risk ──
  const riskSigs: ScoringSignal[] = []; const riskLabels: ScoreLabel[] = [];
  let riskScore = secScore * 0.5 + liqScore * 0.5;
  if (holders < 50)   { riskScore = clamp(riskScore - 20); riskLabels.push("low-holders"); sig(riskSigs, `Only ${holders} holders — very thin community`, -20, "risk"); }
  else if (holders < 200) { riskScore = clamp(riskScore - 10); riskLabels.push("low-holders"); sig(riskSigs, `${holders} holders — limited adoption`, -10, "risk"); }
  else if (holders >= 1000) { sig(riskSigs, `${holders.toLocaleString()} holders — healthy community`, +8, "risk"); }
  if (ageMin < 30)    { riskScore = clamp(riskScore - 15); riskLabels.push("new-token"); sig(riskSigs, `Token is only ${ageMin}m old — very new, high risk`, -15, "risk"); }
  else if (ageMin < 120) { riskScore = clamp(riskScore - 8); riskLabels.push("new-token"); sig(riskSigs, `Token is ${ageMin}m old — early stage`, -8, "risk"); }
  if (pct24h < -30)   { riskScore = clamp(riskScore - 10); sig(riskSigs, `Price down ${pct24h.toFixed(1)}% in 24h — possible exit`, -10, "risk"); }
  riskScore = clamp(riskScore);

  // ── Momentum ──
  const momSigs: ScoringSignal[] = []; const momLabels: ScoreLabel[] = [];
  let momScore = 50;
  if (pct24h >= 200)   { momScore += 40; momLabels.push("price-breakout"); sig(momSigs, `Price +${pct24h.toFixed(0)}% in 24h — parabolic momentum`, +40, "momentum"); }
  else if (pct24h >= 80) { momScore += 30; momLabels.push("price-breakout"); sig(momSigs, `Price +${pct24h.toFixed(0)}% in 24h — breakout momentum`, +30, "momentum"); }
  else if (pct24h >= 20) { momScore += 18; momLabels.push("trending"); sig(momSigs, `Price +${pct24h.toFixed(0)}% in 24h — strong uptrend`, +18, "momentum"); }
  else if (pct24h >= 5)  { momScore += 8; sig(momSigs, `Price +${pct24h.toFixed(0)}% in 24h — mild positive`, +8, "momentum"); }
  else if (pct24h < -30) { momScore -= 30; sig(momSigs, `Price ${pct24h.toFixed(0)}% in 24h — severe downtrend`, -30, "momentum"); }
  else if (pct24h < -10) { momScore -= 15; sig(momSigs, `Price ${pct24h.toFixed(0)}% in 24h — downtrend`, -15, "momentum"); }
  if (vol24h >= 20_000_000) { momScore += 20; momLabels.push("high-volume"); sig(momSigs, `$${(vol24h / 1e6).toFixed(1)}M volume — extreme activity`, +20, "momentum"); }
  else if (vol24h >= 5_000_000) { momScore += 12; momLabels.push("high-volume"); sig(momSigs, `$${(vol24h / 1e6).toFixed(1)}M volume — high activity`, +12, "momentum"); }
  else if (vol24h >= 500_000) { momScore += 5; sig(momSigs, `$${(vol24h / 1e3).toFixed(0)}K volume — moderate activity`, +5, "momentum"); }
  else if (vol24h < 5_000) { momScore -= 15; sig(momSigs, "Volume < $5K — near-zero trading activity", -15, "momentum"); }
  if (volChg > 100) { momScore += 10; momLabels.push("volume-spike"); sig(momSigs, `Volume up ${volChg.toFixed(0)}% vs yesterday — volume surge`, +10, "momentum"); }
  else if (volChg < -50) { momScore -= 8; sig(momSigs, `Volume down ${Math.abs(volChg).toFixed(0)}% — fading interest`, -8, "momentum"); }
  if (pct24h > 5 && volChg > 20) { momScore += 8; momLabels.push("breakout"); sig(momSigs, "Price + volume both rising — confirmed breakout signal", +8, "momentum"); }
  else if (pct24h > 5 && volChg < -20) { momScore -= 5; sig(momSigs, "Price rising on falling volume — weak, unconfirmed move", -5, "momentum"); }
  momScore = clamp(momScore);

  // ── Opportunity ──
  const oppSigs: ScoringSignal[] = []; const oppLabels: ScoreLabel[] = [];
  let oppScore = momScore * 0.6 + riskScore * 0.4;
  if (mc > 0 && mc < 500_000) { oppScore += 15; oppLabels.push("low-mcap-gem"); sig(oppSigs, `Micro-cap (${(mc / 1e3).toFixed(0)}K mcap) — high upside potential`, +15, "opportunity"); }
  else if (mc < 5_000_000) { oppScore += 8; oppLabels.push("low-mcap-gem"); sig(oppSigs, "Small-cap — room to grow vs large caps", +8, "opportunity"); }
  else if (mc >= 50_000_000) { oppScore -= 5; sig(oppSigs, "Large-cap — limited explosive upside", -5, "opportunity"); }
  if (ageMin < 60 && riskScore >= 50) { oppScore += 10; sig(oppSigs, "Early entry opportunity — token < 1h old", +10, "opportunity"); }
  if (riskScore < 30)  { oppScore = clamp(oppScore - 20); sig(oppSigs, "Very high risk significantly reduces opportunity rating", -20, "opportunity"); }
  else if (riskScore < 50) { oppScore = clamp(oppScore - 10); sig(oppSigs, "Elevated risk discounts opportunity score", -10, "opportunity"); }
  oppScore = clamp(oppScore);

  const overall = clamp(Math.round(
    riskScore * 0.30 + oppScore * 0.25 + momScore * 0.20 + liqScore * 0.15 + secScore * 0.10,
  ));

  const allLabels: ScoreLabel[] = Array.from(new Set([...liqLabels, ...secLabels, ...riskLabels, ...momLabels, ...oppLabels]));
  const allSignals = [...liqSigs, ...secSigs, ...riskSigs, ...momSigs, ...oppSigs];

  let verdict: Verdict; let verdictReason: string;
  if (secScore < 25 || riskScore < 20) {
    verdict = "AVOID"; verdictReason = "Critical security flags or critically low risk score.";
  } else if (riskScore >= 60 && secScore >= 55 && oppScore >= 70 && momScore >= 65) {
    verdict = "BUY"; verdictReason = "Strong opportunity signal backed by healthy risk profile and momentum.";
  } else if (overall >= 72 && riskScore >= 55 && !allLabels.includes("low-liquidity")) {
    verdict = "BUY"; verdictReason = "High composite score with acceptable liquidity and risk.";
  } else if (allLabels.includes("breakout") && riskScore >= 60) {
    verdict = "BUY"; verdictReason = "Confirmed breakout on a relatively safe token.";
  } else if (overall < 30) {
    verdict = "AVOID"; verdictReason = "Low composite score across all dimensions.";
  } else {
    verdict = "WATCH";
    const parts: string[] = [];
    if (oppScore >= 60) parts.push("decent opportunity upside");
    if (riskScore >= 55) parts.push("manageable risk");
    if (momScore >= 60) parts.push("positive momentum");
    if (allLabels.includes("new-token")) parts.push("very new token needs monitoring");
    verdictReason = parts.length ? `Monitor closely — ${parts.join(", ")}.` : "Mixed signals — insufficient confidence for entry.";
  }

  return {
    overall,
    risk: Math.round(riskScore),
    opportunity: Math.round(oppScore),
    momentum: Math.round(momScore),
    liquidity: Math.round(liqScore),
    security: Math.round(secScore),
    verdict, verdictReason, labels: allLabels, signals: allSignals, confidence: 0.5,
  };
}

// ─── Rule-based insight ───────────────────────────────────────────────────────

function buildInsight(t: TokenOverview, score: TokenScore): string {
  const liq = t.liquidity; const pct = t.priceChange24hPercent;
  const liqSentence =
    liq >= 5_000_000 ? `Liquidity is excellent at $${(liq / 1e6).toFixed(1)}M — deep enough to absorb large orders without meaningful slippage.` :
    liq >= 1_000_000 ? `Liquidity of $${(liq / 1e6).toFixed(1)}M is solid, providing reliable entry and exit depth for most position sizes.` :
    liq >= 250_000   ? `Liquidity stands at $${(liq / 1e3).toFixed(0)}K — sufficient for small to mid-sized positions, but watch for widening spreads on larger trades.` :
    liq >= 50_000    ? `Liquidity is thin at $${(liq / 1e3).toFixed(0)}K — even moderate buy or sell pressure can cause notable price impact.` :
                       `Liquidity is critically low at $${(liq / 1e3).toFixed(0)}K — exit risk is very high; treat any entry with extreme caution.`;
  const priceSentence =
    pct >= 100 ? `Price has surged ${pct.toFixed(0)}% in the last 24h — momentum is extreme. Watch for a potential reversion after this sharp move.` :
    pct >= 20  ? `The token is up ${pct.toFixed(0)}% in 24h, showing strong buying pressure and a confirmed uptrend.` :
    pct >= 5   ? `A ${pct.toFixed(0)}% gain in 24h reflects healthy demand. The trend is constructive but not yet parabolic.` :
    pct >= -5  ? `Price is essentially flat over 24h — consolidation, which can precede a breakout in either direction.` :
    pct >= -20 ? `A ${Math.abs(pct).toFixed(0)}% decline in 24h signals selling pressure. Wait for stabilization before any entry.` :
                 `A severe ${Math.abs(pct).toFixed(0)}% drop in 24h suggests significant distribution or loss of market confidence.`;
  const riskSentence =
    score.risk >= 75 ? `Overall risk profile is favourable — liquidity, holder distribution, and market metrics are all in acceptable ranges.` :
    score.risk >= 55 ? `Risk is moderate. The token shows some concerns that warrant careful position sizing.` :
                       `Risk is elevated. Multiple factors — including thin liquidity, concentrated supply, or very low holder count — increase the probability of adverse moves.`;
  return `${liqSentence} ${priceSentence} ${riskSentence} Overall verdict: ${score.verdict} (score ${score.overall}/100). ${score.verdictReason}`;
}

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtPrice(n: number): string {
  if (!n || !isFinite(n)) return "$0";
  if (n < 0.000001) return `$${n.toExponential(2)}`;
  if (n < 0.01) return `$${n.toFixed(6)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n);
}
function fmtNum(n: number): string {
  if (!n || !isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  return n.toFixed(2);
}
function fmtPct(n: number): string { return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`; }
function fmtAddr(a: string, c = 4): string { return a.length < c * 2 + 3 ? a : `${a.slice(0, c)}...${a.slice(-c)}`; }
function pctColor(n: number): string { return n > 0 ? "text-buy" : n < 0 ? "text-sell" : "text-muted-foreground"; }
function scoreTextColor(n: number): string { return n >= 75 ? "text-buy" : n >= 50 ? "text-yellow-400" : "text-sell"; }
function scoreBarColor(n: number): string { return n >= 75 ? "bg-buy" : n >= 50 ? "bg-yellow-400" : "bg-sell"; }
function scoreRating(n: number): string { return n >= 75 ? "HIGH" : n >= 50 ? "MED" : "LOW"; }

// ─── Sparkline ────────────────────────────────────────────────────────────────

function generateSparkPath(priceChange: number, volume: number, w = 300, h = 64): string {
  const pts = 14; const step = w / (pts - 1); const seed = Math.abs(volume % 998) + 1;
  const ys: number[] = []; let cur = h * 0.5;
  for (let i = 0; i < pts; i++) {
    const trend = (priceChange / 100) * h * 0.3;
    const noise = ((((seed * (i + 1) * 17) % 100) / 100) - 0.5) * h * 0.4;
    cur = Math.max(4, Math.min(h - 4, cur + trend / pts + noise));
    ys.push(cur);
  }
  return ys.map((y, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${y.toFixed(1)}`).join(" ");
}

function Sparkline({ priceChange, volume }: { priceChange: number; volume: number }) {
  const W = 300; const H = 64;
  const path  = generateSparkPath(priceChange, volume, W, H);
  const color = priceChange >= 0 ? "#00A86B" : "#DC2626";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none">
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${path} L${W},${H} L0,${H} Z`} fill="url(#spark-fill)" />
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, icon, change }: {
  label: string; value: string; sub?: string; icon: React.ReactNode; change?: number;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">{label}</span>
        <span className="text-muted-foreground">{icon}</span>
      </div>
      <div>
        <p className="font-mono text-xl font-bold text-foreground">{value}</p>
        {sub && <p className="mt-0.5 font-mono text-xs text-muted-foreground">{sub}</p>}
        {change !== undefined && <p className={`mt-0.5 font-mono text-xs font-semibold ${pctColor(change)}`}>{fmtPct(change)} 24h</p>}
      </div>
    </div>
  );
}

function ScoreCard({ label, score, description }: { label: string; score: number; description: string }) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 transition-all hover:-translate-y-0.5 hover:shadow-lg">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-foreground">{label}</span>
        <span className={`font-mono text-lg font-bold tabular-nums ${scoreTextColor(score)}`}>{score}</span>
      </div>
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className={`font-mono text-[10px] font-bold ${scoreTextColor(score)}`}>{score}/100</span>
          <span className={`font-mono text-[10px] font-semibold uppercase tracking-widest ${scoreTextColor(score)}`}>{scoreRating(score)}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div className={`h-full rounded-full transition-[width] duration-700 ${scoreBarColor(score)}`} style={{ width: `${score}%` }} />
        </div>
      </div>
      <p className="font-mono text-[10px] leading-relaxed text-muted-foreground">{description}</p>
    </div>
  );
}

type VerdictStyle = { border: string; bg: string; text: string; icon: React.ReactNode };
const VERDICT_STYLES: Record<Verdict, VerdictStyle> = {
  BUY:   { border: "border-buy/30",        bg: "bg-buy/5",        text: "text-buy",        icon: <CheckCircle2 className="h-5 w-5" /> },
  WATCH: { border: "border-yellow-400/30", bg: "bg-yellow-400/5", text: "text-yellow-400", icon: <AlertTriangle className="h-5 w-5" /> },
  AVOID: { border: "border-sell/30",       bg: "bg-sell/5",       text: "text-sell",       icon: <XCircle className="h-5 w-5" /> },
};

function VerdictBanner({ score }: { score: TokenScore }) {
  const s = VERDICT_STYLES[score.verdict];
  return (
    <div className={`flex items-start gap-3 rounded-xl border p-4 ${s.border} ${s.bg}`}>
      <span className={s.text}>{s.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-sm font-bold ${s.text}`}>{score.verdict}</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs text-muted-foreground">Score: <span className={`font-mono font-bold ${s.text}`}>{score.overall}</span></span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs text-muted-foreground">Confidence: {Math.round(score.confidence * 100)}%</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{score.verdictReason}</p>
      </div>
    </div>
  );
}

const LABEL_STYLES: Record<ScoreLabel, string> = {
  "high-risk": "border-sell/30 bg-sell/10 text-sell", "low-liquidity": "border-yellow-400/30 bg-yellow-400/10 text-yellow-400",
  "new-token": "border-cyan/30 bg-cyan/10 text-cyan", "trending": "border-cyan/30 bg-cyan/10 text-cyan",
  "breakout": "border-buy/30 bg-buy/10 text-buy", "whale-activity": "border-yellow-400/30 bg-yellow-400/10 text-yellow-400",
  "low-holders": "border-sell/30 bg-sell/10 text-sell", "high-volume": "border-buy/30 bg-buy/10 text-buy",
  "concentrated-supply": "border-sell/30 bg-sell/10 text-sell", "lp-burned": "border-buy/30 bg-buy/10 text-buy",
  "mintable": "border-sell/30 bg-sell/10 text-sell", "freezeable": "border-sell/30 bg-sell/10 text-sell",
  "transfer-fee": "border-yellow-400/30 bg-yellow-400/10 text-yellow-400", "mutable-metadata": "border-yellow-400/30 bg-yellow-400/10 text-yellow-400",
  "volume-spike": "border-cyan/30 bg-cyan/10 text-cyan", "price-breakout": "border-buy/30 bg-buy/10 text-buy",
  "low-mcap-gem": "border-cyan/30 bg-cyan/10 text-cyan", "honeypot-risk": "border-sell/30 bg-sell/10 text-sell",
};

function AIPanel({ insight, source }: { insight: string; source: "groq" | "rule-based" }) {
  return (
    <div className="rounded-xl border border-cyan/20 bg-cyan/5 p-5 ring-1 ring-cyan/10">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-cyan" />
        <span className="text-sm font-semibold text-cyan">AI Insight</span>
        <span className="inline-flex items-center rounded-full border border-border bg-muted/60 px-2 py-0.5 font-mono text-[9px] font-bold text-muted-foreground">
          {source === "groq" ? "Groq" : "Rule-based"}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{insight}</p>
    </div>
  );
}

function SecurityFlagChip({ on, label }: { on: boolean; label: string }) {
  return (
    <div className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-[10px] ${on ? "border-sell/30 bg-sell/10 text-sell" : "border-buy/30 bg-buy/10 text-buy"}`}>
      <span>{on ? "RISK" : "OK"}</span>
      <span className="opacity-80">{label}</span>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function TokenDetailPage() {
  const params  = useParams();
  const address = typeof params.address === "string" ? params.address : (Array.isArray(params.address) ? params.address[0] : "");

  const [token, setToken]     = useState<TokenOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [aiInsight, setAiInsight] = useState<string>("");
  const [aiSource, setAiSource] = useState<"groq" | "rule-based">("rule-based");

  // ── Intelligence panels state ──
  const [activeTab, setActiveTab] = useState<IntelTab>("top-traders");
  const [topTraders, setTopTraders]         = useState<TopTrader[] | null>(null);
  const [holderData, setHolderData]         = useState<HolderData | null>(null);
  const [tradeFlow, setTradeFlow]           = useState<TradeFlowData | null>(null);
  const [exitLiquidity, setExitLiquidity]   = useState<ExitLiquidityData | null>(null);
  const [priceStats, setPriceStats]         = useState<PriceStatsData | null>(null);
  const [tabLoading, setTabLoading]         = useState(false);

  const fetchToken = useCallback(async () => {
    if (!address) return;
    setLoading(true); setError(null);
    try {
      const [overviewRes, insightRes] = await Promise.all([
        fetch(`${API_BASE}/api/tokens/${address}/overview`),
        fetch(`${API_BASE}/api/tokens/${address}/insight`),
      ]);
      if (!overviewRes.ok) throw new Error(`HTTP ${overviewRes.status}`);
      const overview = (await overviewRes.json()) as TokenOverview;
      setToken(overview);

      if (insightRes.ok) {
        const insightJson = (await insightRes.json()) as { insight?: string; source?: "groq" | "rule-based" };
        setAiInsight(insightJson.insight || "");
        setAiSource(insightJson.source === "groq" && !!insightJson.insight ? "groq" : "rule-based");
      } else {
        setAiInsight("");
        setAiSource("rule-based");
      }
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [address]);

  const fetchTab = useCallback(async (tab: IntelTab) => {
    if (!address) return;
    setTabLoading(true);
    try {
      if (tab === "top-traders" && topTraders === null) {
        const res = await fetch(`${API_BASE}/api/tokens/${address}/top-traders`);
        if (res.ok) setTopTraders(await res.json() as TopTrader[]);
        else setTopTraders([]);
      } else if (tab === "holders" && holderData === null) {
        const res = await fetch(`${API_BASE}/api/tokens/${address}/holders`);
        if (res.ok) setHolderData(await res.json() as HolderData);
      } else if (tab === "trade-flow" && tradeFlow === null) {
        const res = await fetch(`${API_BASE}/api/tokens/${address}/trade-data`);
        if (res.ok) setTradeFlow(await res.json() as TradeFlowData);
      } else if (tab === "exit-liquidity" && exitLiquidity === null) {
        const res = await fetch(`${API_BASE}/api/tokens/${address}/exit-liquidity`);
        if (res.ok) setExitLiquidity(await res.json() as ExitLiquidityData);
      } else if (tab === "price-stats" && priceStats === null) {
        const res = await fetch(`${API_BASE}/api/tokens/${address}/price-stats`);
        if (res.ok) setPriceStats(await res.json() as PriceStatsData);
      }
    } catch { /* silent */ }
    finally { setTabLoading(false); }
  }, [address, topTraders, holderData, tradeFlow, exitLiquidity, priceStats]);

  useEffect(() => { void fetchTab(activeTab); }, [activeTab, fetchTab]);

  useEffect(() => {
    const id = setTimeout(() => {
      void fetchToken();
    }, 0);
    return () => clearTimeout(id);
  }, [fetchToken]);

  // ── Loading ──
  if (loading) {
    return (
      <div className="min-h-screen flex flex-col">
        <NavBar />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 space-y-6">
          <div className="h-4 w-32 animate-pulse rounded bg-muted" />
          <div className="h-52 animate-pulse rounded-xl bg-card" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-card" />)}
          </div>
          <div className="h-28 animate-pulse rounded-xl bg-card" />
          <div className="h-96 animate-pulse rounded-xl bg-card" />
        </main>
      </div>
    );
  }

  // ── Error ──
  if (error || !token) {
    return (
      <div className="min-h-screen flex flex-col">
        <NavBar />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 space-y-6">
          <Link href="/dashboard" className="inline-flex items-center gap-1.5 font-mono text-sm text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-4 w-4" /> Back to Dashboard
          </Link>
          <div className="flex flex-col items-center gap-4 rounded-xl border border-sell/20 bg-sell/5 py-20 text-center">
            <ShieldOff className="h-10 w-10 text-sell" />
            <div>
              <p className="font-semibold text-sell">Token data unavailable</p>
              <p className="mt-1 max-w-xs font-mono text-sm text-muted-foreground">
                This token may not yet be indexed, or the API is temporarily unavailable.
              </p>
              <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{address}</p>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={fetchToken} className="rounded-lg border border-border bg-card px-4 py-2 font-mono text-sm text-muted-foreground transition-colors hover:text-foreground">
                Retry
              </button>
              <Link href="/dashboard" className="rounded-lg bg-muted px-4 py-2 font-mono text-sm text-muted-foreground transition-colors hover:text-foreground">
                Return to Dashboard
              </Link>
            </div>
          </div>
        </main>
      </div>
    );
  }

  const score   = scoreToken(token);
  const insight = aiInsight || buildInsight(token, score);

  const LINKS = [
    { href: `https://solscan.io/token/${address}`,              label: "Solscan" },
    { href: `https://dexscreener.com/solana/${address}`,        label: "DexScreener" },
    { href: `https://birdeye.so/token/${address}?chain=solana`, label: "Birdeye" },
  ];

  const heroBorder = score.verdict === "BUY" ? "border-buy/30" : score.verdict === "AVOID" ? "border-sell/30" : "border-border";

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 space-y-6">

        {/* ── Back ─── */}
        <Link href="/dashboard" className="inline-flex items-center gap-1.5 font-mono text-sm text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Back to Dashboard
        </Link>

        {/* ── Hero card ─── */}
        <div className={`flex flex-col gap-5 rounded-xl border bg-card p-6 sm:flex-row sm:items-start ${heroBorder}`}>
          {/* Logo */}
          <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-2xl bg-muted">
            <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-muted-foreground">
              {token.symbol.slice(0, 2).toUpperCase()}
            </span>
            {token.logoURI && (
              <Image src={token.logoURI} alt={token.symbol} fill unoptimized className="rounded-2xl object-cover" />
            )}
          </div>
          {/* Info */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-foreground">{token.name}</h1>
              <span className="font-mono text-base text-muted-foreground">{token.symbol}</span>
              <span className="inline-flex items-center rounded-full border border-cyan/20 bg-cyan/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-cyan">
                Solana
              </span>
              {score.verdict === "BUY" && (
                <span className="inline-flex items-center rounded-full border border-buy/20 bg-buy/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-buy">BUY</span>
              )}
              {score.verdict === "AVOID" && (
                <span className="inline-flex items-center rounded-full border border-sell/20 bg-sell/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-sell">AVOID</span>
              )}
              {score.verdict === "WATCH" && (
                <span className="inline-flex items-center rounded-full border border-yellow-400/20 bg-yellow-400/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-yellow-400">WATCH</span>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span className="font-mono">{fmtAddr(address, 8)}</span>
              {LINKS.map((lnk) => (
                <a key={lnk.href} href={lnk.href} target="_blank" rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-muted-foreground transition-colors hover:text-cyan">
                  {lnk.label} <ExternalLink className="h-3 w-3" />
                </a>
              ))}
            </div>
            {/* Sparkline + price */}
            <div className="mt-4 flex items-end gap-4">
              <div className="min-w-0 flex-1">
                <Sparkline priceChange={token.priceChange24hPercent} volume={token.v24hUSD} />
              </div>
              <div className="shrink-0 text-right">
                <p className="font-mono text-2xl font-bold text-foreground">{fmtPrice(token.price)}</p>
                <p className={`font-mono text-sm font-bold ${pctColor(token.priceChange24hPercent)}`}>
                  {fmtPct(token.priceChange24hPercent)} 24h
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* ── Verdict banner ─── */}
        <VerdictBanner score={score} />

        {/* ── Key metrics ─── */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard label="Volume 24h"   value={`$${fmtNum(token.v24hUSD)}`}       change={token.v24hChangePercent} icon={<BarChart2 className="h-4 w-4" />} />
          <StatCard label="Market Cap"   value={`$${fmtNum(token.mc)}`}             icon={<TrendingUp className="h-4 w-4" />} />
          <StatCard label="Liquidity"    value={`$${fmtNum(token.liquidity)}`}      icon={<Droplets className="h-4 w-4" />} />
          <StatCard label="Holders"      value={token.holder.toLocaleString()}      icon={<Users className="h-4 w-4" />} />
          <StatCard label="Circulating"  value={fmtNum(token.circulatingSupply)}    sub={`of ${fmtNum(token.supply)} total`} icon={<Zap className="h-4 w-4" />} />
          <StatCard label="Real Mkt Cap" value={`$${fmtNum(token.realMc)}`}         icon={<BarChart2 className="h-4 w-4" />} />
        </div>

        {/* ── AI insight ─── */}
        <AIPanel insight={insight} source={aiInsight ? aiSource : "rule-based"} />

        {/* ── Chart ─── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <CandlestickChart className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Price Chart</h2>
          </div>
          <OHLCVChart address={address} symbol={token.symbol} />
        </section>

        {/* ── Score breakdown ─── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Score Breakdown</h2>
            <span className="font-mono text-xs text-muted-foreground">
              Composite: <span className={`font-bold ${scoreTextColor(score.overall)}`}>{score.overall}/100</span>
            </span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <ScoreCard label="Risk"        score={score.risk}        description="Higher = safer. Factors in age, holder count, and liquidity floor." />
            <ScoreCard label="Opportunity" score={score.opportunity} description="Upside potential from price action, market cap, and momentum." />
            <ScoreCard label="Momentum"    score={score.momentum}    description="Volume trend, price acceleration, and buy/sell confirmation." />
            <ScoreCard label="Liquidity"   score={score.liquidity}   description="Depth of on-chain pools — determines entry and exit ease." />
            <ScoreCard label="Security"    score={score.security}    description="Uses Birdeye premium token-security flags plus holder/liquidity context." />
          </div>
        </section>

        {/* ── Security panel ─── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Security Flags</h2>
            <span className="inline-flex items-center rounded-full border border-buy/30 bg-buy/10 px-2 py-0.5 font-mono text-[9px] font-bold text-buy">
              Live (Premium)
            </span>
          </div>
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="mb-4 flex flex-wrap gap-2">
              <SecurityFlagChip on={token.securityFlags.mintable} label="Mintable" />
              <SecurityFlagChip on={token.securityFlags.freezeable} label="Freezeable" />
              <SecurityFlagChip on={token.securityFlags.mutableMetadata} label="Mutable Metadata" />
              <SecurityFlagChip on={token.securityFlags.transferFee} label="Transfer Fee" />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-border p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Security Score</p>
                <p className="font-mono text-sm font-bold text-foreground">{typeof token.securityScore === "number" ? `${Math.round(token.securityScore)}/100` : "N/A"}</p>
              </div>
              <div className="rounded-lg border border-border p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Top 10 Holders</p>
                <p className="font-mono text-sm font-bold text-foreground">{typeof token.securityFlags.top10HolderPct === "number" ? `${token.securityFlags.top10HolderPct.toFixed(1)}%` : "N/A"}</p>
              </div>
              <div className="rounded-lg border border-border p-3">
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Risk Verdict</p>
                <p className={`font-mono text-sm font-bold ${score.security >= 70 ? "text-buy" : score.security >= 50 ? "text-yellow-400" : "text-sell"}`}>
                  {score.security >= 70 ? "LOW" : score.security >= 50 ? "MED" : "HIGH"}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── Detected labels ─── */}
        {score.labels.length > 0 && (
          <section>
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold text-foreground">Detected Labels</h2>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {score.labels.map((lbl) => (
                <span key={lbl} className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider ${LABEL_STYLES[lbl]}`}>
                  {lbl}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* ── Scoring signals ─── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <BarChart2 className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Scoring Signals</h2>
            <span className="font-mono text-xs text-muted-foreground">{score.signals.length} signals</span>
          </div>
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="divide-y divide-border/50">
              {score.signals.map((s, i) => (
                <div key={i} className="flex items-start gap-3 px-4 py-3">
                  <span className={`mt-0.5 w-10 shrink-0 font-mono text-[10px] font-bold tabular-nums ${s.impact === "positive" ? "text-buy" : s.impact === "negative" ? "text-sell" : "text-muted-foreground"}`}>
                    {s.delta > 0 ? "+" : ""}{s.delta}
                  </span>
                  <p className="flex-1 text-sm text-muted-foreground">{s.label}</p>
                  <span className="shrink-0 inline-flex items-center rounded-full border border-border bg-muted/60 px-2 py-0.5 font-mono text-[9px] font-bold text-muted-foreground">
                    {s.category}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Token Intelligence Panel (Phase 1 — 5 premium endpoint tabs) ─── */}
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Layers className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">Token Intelligence</h2>
            <span className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-mono text-[9px] font-bold text-cyan">
              5 Premium Endpoints
            </span>
          </div>

          {/* Tab bar */}
          <div className="flex flex-wrap gap-1 rounded-xl border border-border bg-card p-1 mb-0">
            {(
              [
                { id: "top-traders",    label: "Top Traders" },
                { id: "holders",        label: "Holders" },
                { id: "trade-flow",     label: "Trade Flow" },
                { id: "exit-liquidity", label: "Exit Liquidity" },
                { id: "price-stats",    label: "Multi-TF Stats" },
              ] as { id: IntelTab; label: string }[]
            ).map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`rounded-lg px-3 py-1.5 font-mono text-[11px] font-semibold transition-colors ${
                  activeTab === t.id
                    ? "bg-cyan/15 text-cyan"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="rounded-xl border border-border bg-card p-5 min-h-50">
            {tabLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
              </div>
            ) : (
              <>
                {/* ── Top Traders ── */}
                {activeTab === "top-traders" && (
                  <div>
                    {!topTraders || topTraders.length === 0 ? (
                      <p className="font-mono text-xs text-muted-foreground py-8 text-center">No trader data available for this token.</p>
                    ) : (
                      <div className="divide-y divide-border/50">
                        {topTraders.map((t, i) => (
                          <div key={t.address} className="flex items-center gap-3 py-3">
                            <span className="w-5 shrink-0 font-mono text-[10px] text-muted-foreground">#{i + 1}</span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                {t.is_tracked ? (
                                  <Link href={`/wallet/${t.address}`} className="font-mono text-xs font-semibold text-cyan hover:underline truncate">
                                    {t.label}
                                  </Link>
                                ) : (
                                  <span className="font-mono text-xs text-foreground truncate">{t.label}</span>
                                )}
                                {t.is_tracked && (
                                  <span className="shrink-0 inline-flex items-center rounded-full border border-buy/30 bg-buy/10 px-1.5 py-0.5 font-mono text-[8px] font-bold text-buy">
                                    TRACKED
                                  </span>
                                )}
                              </div>
                              <p className="font-mono text-[10px] text-muted-foreground truncate">{t.address.slice(0, 12)}…</p>
                            </div>
                            <div className="shrink-0 text-right">
                              <p className={`font-mono text-xs font-bold ${t.pnl_usd >= 0 ? "text-buy" : "text-sell"}`}>
                                {t.pnl_usd >= 0 ? "+" : ""}${Math.abs(t.pnl_usd) >= 1000 ? `${(t.pnl_usd / 1000).toFixed(1)}K` : t.pnl_usd.toFixed(0)}
                              </p>
                              <p className="font-mono text-[10px] text-muted-foreground">{t.trade_count} trades · {(t.win_rate * 100).toFixed(0)}% WR</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Holders ── */}
                {activeTab === "holders" && (
                  <div>
                    {!holderData ? (
                      <p className="font-mono text-xs text-muted-foreground py-8 text-center">No holder data available.</p>
                    ) : (
                      <div className="space-y-4">
                        <div className="grid grid-cols-3 gap-3">
                          <div className="rounded-lg border border-border p-3">
                            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Total Holders</p>
                            <p className="font-mono text-lg font-bold text-foreground mt-1">{holderData.total_holders.toLocaleString()}</p>
                          </div>
                          <div className="rounded-lg border border-border p-3">
                            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Top 10 Own</p>
                            <p className="font-mono text-lg font-bold text-foreground mt-1">{holderData.top10_pct.toFixed(1)}%</p>
                          </div>
                          <div className="rounded-lg border border-border p-3">
                            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Concentration</p>
                            <p className={`font-mono text-sm font-bold mt-1 ${holderData.concentration_risk === "HIGH" ? "text-sell" : holderData.concentration_risk === "MODERATE" ? "text-yellow-400" : "text-buy"}`}>
                              {holderData.concentration_risk}
                            </p>
                          </div>
                        </div>
                        {/* Top holders bar chart */}
                        <div>
                          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Top 10 Holder Breakdown</p>
                          <div className="space-y-1.5">
                            {holderData.top10.map((h, i) => (
                              <div key={i} className="flex items-center gap-2">
                                <span className="w-4 shrink-0 font-mono text-[9px] text-muted-foreground">#{i + 1}</span>
                                <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                                  <div
                                    className="h-full rounded-full bg-cyan/60"
                                    style={{ width: `${Math.min(100, h.pct)}%` }}
                                  />
                                </div>
                                <span className="w-10 shrink-0 text-right font-mono text-[10px] text-muted-foreground">{h.pct.toFixed(1)}%</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* ── Trade Flow ── */}
                {activeTab === "trade-flow" && (
                  <div>
                    {!tradeFlow ? (
                      <p className="font-mono text-xs text-muted-foreground py-8 text-center">No trade flow data available.</p>
                    ) : (
                      <div className="space-y-4">
                        {/* Pressure badge */}
                        <div className="flex items-center gap-3">
                          <span className={`inline-flex items-center rounded-full px-3 py-1 font-mono text-sm font-bold ring-1 ${
                            tradeFlow.pressure === "BUY"
                              ? "bg-buy/10 text-buy ring-buy/30"
                              : tradeFlow.pressure === "SELL"
                              ? "bg-sell/10 text-sell ring-sell/30"
                              : "bg-yellow-400/10 text-yellow-400 ring-yellow-400/30"
                          }`}>
                            {tradeFlow.pressure} PRESSURE
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">
                            {(tradeFlow.buy_ratio * 100).toFixed(1)}% of trades are buys
                          </span>
                        </div>
                        {/* Buy vs Sell count bar */}
                        <div>
                          <div className="mb-1.5 flex justify-between font-mono text-[10px] text-muted-foreground">
                            <span>BUY {tradeFlow.buy_count.toLocaleString()}</span>
                            <span>SELL {tradeFlow.sell_count.toLocaleString()}</span>
                          </div>
                          <div className="flex h-3 overflow-hidden rounded-full bg-muted">
                            <div className="bg-buy/70 transition-[width] duration-700" style={{ width: `${tradeFlow.buy_ratio * 100}%` }} />
                            <div className="bg-sell/70 flex-1" />
                          </div>
                        </div>
                        {/* Volume row */}
                        <div className="grid grid-cols-2 gap-3">
                          <div className="rounded-lg border border-buy/20 bg-buy/5 p-3">
                            <p className="font-mono text-[10px] uppercase tracking-wider text-buy">Buy Volume 24h</p>
                            <p className="font-mono text-sm font-bold text-foreground mt-1">
                              ${tradeFlow.buy_volume_usd >= 1_000_000 ? `${(tradeFlow.buy_volume_usd / 1e6).toFixed(2)}M` : tradeFlow.buy_volume_usd >= 1_000 ? `${(tradeFlow.buy_volume_usd / 1e3).toFixed(1)}K` : tradeFlow.buy_volume_usd.toFixed(0)}
                            </p>
                          </div>
                          <div className="rounded-lg border border-sell/20 bg-sell/5 p-3">
                            <p className="font-mono text-[10px] uppercase tracking-wider text-sell">Sell Volume 24h</p>
                            <p className="font-mono text-sm font-bold text-foreground mt-1">
                              ${tradeFlow.sell_volume_usd >= 1_000_000 ? `${(tradeFlow.sell_volume_usd / 1e6).toFixed(2)}M` : tradeFlow.sell_volume_usd >= 1_000 ? `${(tradeFlow.sell_volume_usd / 1e3).toFixed(1)}K` : tradeFlow.sell_volume_usd.toFixed(0)}
                            </p>
                          </div>
                        </div>
                        <p className="font-mono text-[10px] text-muted-foreground">{tradeFlow.total_trades.toLocaleString()} total trades in last 24h</p>
                      </div>
                    )}
                  </div>
                )}

                {/* ── Exit Liquidity ── */}
                {activeTab === "exit-liquidity" && (
                  <div>
                    {!exitLiquidity ? (
                      <p className="font-mono text-xs text-muted-foreground py-8 text-center">No exit liquidity data available.</p>
                    ) : (
                      <div className="space-y-4">
                        {/* Rating badge + total */}
                        <div className="flex items-center gap-3">
                          <span className={`inline-flex items-center rounded-full px-3 py-1 font-mono text-sm font-bold ring-1 ${
                            exitLiquidity.rating === "DEEP"     ? "bg-buy/10 text-buy ring-buy/30" :
                            exitLiquidity.rating === "ADEQUATE" ? "bg-cyan/10 text-cyan ring-cyan/30" :
                            exitLiquidity.rating === "THIN"     ? "bg-yellow-400/10 text-yellow-400 ring-yellow-400/30" :
                                                                  "bg-sell/10 text-sell ring-sell/30"
                          }`}>
                            {exitLiquidity.rating}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">
                            ${exitLiquidity.total_liquidity_usd >= 1_000_000 ? `${(exitLiquidity.total_liquidity_usd / 1e6).toFixed(2)}M` : `${(exitLiquidity.total_liquidity_usd / 1e3).toFixed(1)}K`} total liquidity
                          </span>
                        </div>
                        {/* Slippage table */}
                        <div>
                          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Slippage Estimates</p>
                          <div className="overflow-hidden rounded-lg border border-border">
                            <table className="w-full">
                              <thead>
                                <tr className="border-b border-border bg-muted/30">
                                  <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Exit Size</th>
                                  <th className="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Est. Slippage</th>
                                  <th className="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Cost</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-border/50">
                                {exitLiquidity.slippage_estimates.map((est) => {
                                  const slipPct = est.slippage_pct ?? 0;
                                  const color = slipPct < 1 ? "text-buy" : slipPct < 3 ? "text-yellow-400" : "text-sell";
                                  return (
                                    <tr key={est.exit_usd}>
                                      <td className="px-4 py-2.5 font-mono text-sm text-foreground">${est.exit_usd.toLocaleString()}</td>
                                      <td className={`px-4 py-2.5 text-right font-mono text-sm font-bold ${color}`}>
                                        {est.slippage_pct != null ? `${est.slippage_pct.toFixed(2)}%` : "N/A"}
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono text-xs text-muted-foreground">
                                        {est.slippage_pct != null ? `~$${((est.exit_usd * est.slippage_pct) / 100).toFixed(0)} lost` : "—"}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                        {exitLiquidity.depth_1pct_usd > 0 && (
                          <div className="grid grid-cols-2 gap-3">
                            <div className="rounded-lg border border-border p-3">
                              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">1% Depth</p>
                              <p className="font-mono text-sm font-bold text-foreground mt-1">${(exitLiquidity.depth_1pct_usd / 1e3).toFixed(1)}K</p>
                            </div>
                            <div className="rounded-lg border border-border p-3">
                              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">2% Depth</p>
                              <p className="font-mono text-sm font-bold text-foreground mt-1">${(exitLiquidity.depth_2pct_usd / 1e3).toFixed(1)}K</p>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Multi-Timeframe Price Stats ── */}
                {activeTab === "price-stats" && (
                  <div>
                    {!priceStats ? (
                      <p className="font-mono text-xs text-muted-foreground py-8 text-center">No price stats available.</p>
                    ) : (
                      <div className="space-y-4">
                        <div className="rounded-lg border border-border bg-muted/20 p-3 flex items-center gap-3">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Current Price</span>
                          <span className="font-mono text-lg font-bold text-foreground">{fmtPrice(priceStats.current_price)}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-3">
                          {(["1h", "4h", "24h"] as const).map((tf) => {
                            const d = priceStats[tf];
                            const chg = d.price_change_pct;
                            return (
                              <div key={tf} className={`rounded-lg border p-3 ${chg >= 0 ? "border-buy/20 bg-buy/5" : "border-sell/20 bg-sell/5"}`}>
                                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">{tf}</p>
                                <p className={`font-mono text-base font-bold ${chg >= 0 ? "text-buy" : "text-sell"}`}>
                                  {chg >= 0 ? "+" : ""}{chg.toFixed(2)}%
                                </p>
                                <div className="mt-2 space-y-0.5">
                                  <p className="font-mono text-[9px] text-muted-foreground">H: {fmtPrice(d.high)}</p>
                                  <p className="font-mono text-[9px] text-muted-foreground">L: {fmtPrice(d.low)}</p>
                                  <p className="font-mono text-[9px] text-muted-foreground">
                                    Vol: ${d.volume_usd >= 1_000_000 ? `${(d.volume_usd / 1e6).toFixed(1)}M` : d.volume_usd >= 1_000 ? `${(d.volume_usd / 1e3).toFixed(0)}K` : d.volume_usd.toFixed(0)}
                                  </p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

      </main>
    </div>
  );
}
