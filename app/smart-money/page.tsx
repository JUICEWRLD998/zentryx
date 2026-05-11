"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { NavBar } from "@/components/navbar";
import { RefreshCw, TrendingUp, TrendingDown, Minus, Zap } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────

interface FlowBucket {
  inflow: number;
  outflow: number;
  net: number;
}

interface SmartMoneyToken {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  "1h": FlowBucket;
  "4h": FlowBucket;
  "24h": FlowBucket;
}

interface HeatmapData {
  tokens: SmartMoneyToken[];
  generated_at: number;
}

type Frame = "1h" | "4h" | "24h";

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

function fmt_usd(n: number): string {
  if (!isFinite(n) || n === 0) return "$0";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

/** Return Tailwind bg/text classes based on net flow value.
 *  Intensity: 4 levels of green (positive) or red (negative), gray for zero.
 */
function flowColor(net: number, maxNet: number): { bg: string; text: string; border: string } {
  if (!isFinite(net) || net === 0 || maxNet === 0) {
    return { bg: "bg-muted/20", text: "text-muted-foreground", border: "border-border/30" };
  }
  const ratio = Math.abs(net) / maxNet;
  if (net > 0) {
    if (ratio > 0.75) return { bg: "bg-buy/25", text: "text-buy", border: "border-buy/40" };
    if (ratio > 0.4)  return { bg: "bg-buy/15", text: "text-buy", border: "border-buy/25" };
    return { bg: "bg-buy/8", text: "text-buy/80", border: "border-buy/15" };
  } else {
    if (ratio > 0.75) return { bg: "bg-sell/25", text: "text-sell", border: "border-sell/40" };
    if (ratio > 0.4)  return { bg: "bg-sell/15", text: "text-sell", border: "border-sell/25" };
    return { bg: "bg-sell/8", text: "text-sell/80", border: "border-sell/15" };
  }
}

// ──────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────

function FlowCell({
  bucket,
  maxNet,
  address,
}: {
  bucket: FlowBucket;
  maxNet: number;
  address: string;
}) {
  const { bg, text, border } = flowColor(bucket.net, maxNet);
  const isPos = bucket.net > 0;
  const isNeg = bucket.net < 0;

  return (
    <Link
      href={`/token/${address}`}
      className={`flex flex-col items-center justify-center rounded-md border p-2 gap-0.5 transition-all hover:scale-105 hover:z-10 cursor-pointer ${bg} ${border}`}
      title={`In: ${fmt_usd(bucket.inflow)} | Out: ${fmt_usd(bucket.outflow)} | Net: ${fmt_usd(bucket.net)}`}
    >
      <span className={`font-mono text-[11px] font-bold ${text}`}>
        {isPos ? "+" : ""}{fmt_usd(bucket.net)}
      </span>
      {isPos ? (
        <TrendingUp size={9} className="text-buy/60 shrink-0" />
      ) : isNeg ? (
        <TrendingDown size={9} className="text-sell/60 shrink-0" />
      ) : (
        <Minus size={9} className="text-muted-foreground/40 shrink-0" />
      )}
    </Link>
  );
}

// ──────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────

export default function SmartMoneyPage() {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortFrame, setSortFrame] = useState<Frame>("24h");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/smart-money/heatmap?limit=20`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Compute max absolute net for color scaling (per selected frame)
  const tokens = data?.tokens ?? [];
  const maxNet = tokens.reduce((m, t) => {
    const n = Math.abs(t[sortFrame].net);
    return n > m ? n : m;
  }, 0);

  // Sort tokens
  const sorted = [...tokens].sort((a, b) => {
    const delta = a[sortFrame].net - b[sortFrame].net;
    return sortDir === "desc" ? -delta : delta;
  });

  const toggleSort = (frame: Frame) => {
    if (sortFrame === frame) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortFrame(frame);
      setSortDir("desc");
    }
  };

  const generatedAt = data?.generated_at
    ? new Date(data.generated_at * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : null;

  const FRAMES: Frame[] = ["1h", "4h", "24h"];

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
                Smart Money Heatmap
              </h1>
              <span className="rounded-full border border-cyan/40 bg-cyan/10 px-2 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-widest text-cyan">
                Premium Endpoint
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground max-w-lg">
              Net smart money inflow / outflow for top tokens across 1H, 4H, and 24H windows.
              Green = accumulating · Red = distributing. Click any token to view its full profile.
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

        {/* Legend */}
        <div className="mb-5 flex flex-wrap items-center gap-3 font-mono text-[10px] text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-buy/8 border border-buy/15" />
            <span>Mild buy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-buy/15 border border-buy/25" />
            <span>Strong buy</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-buy/25 border border-buy/40" />
            <span>Heavy buy</span>
          </div>
          <div className="mx-2 h-3 w-px bg-border" />
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-sell/8 border border-sell/15" />
            <span>Mild sell</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-sell/15 border border-sell/25" />
            <span>Strong sell</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-5 rounded bg-sell/25 border border-sell/40" />
            <span>Heavy sell</span>
          </div>
        </div>

        {loading && !data ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
            <p className="font-mono text-xs text-muted-foreground">
              Fetching smart money flows from Birdeye…
            </p>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-sell/30 bg-sell/5 p-8 text-center">
            <p className="font-mono text-sm text-sell">Failed to load heatmap: {error}</p>
            <button
              onClick={fetchData}
              className="mt-4 rounded-md border border-border/60 bg-card px-4 py-2 font-mono text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Retry
            </button>
          </div>
        ) : sorted.length === 0 ? (
          <div className="rounded-xl border border-border bg-muted/10 p-8 text-center">
            <p className="font-mono text-sm text-muted-foreground">No smart money tokens found.</p>
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            {/* Column headers */}
            <div className="grid grid-cols-[minmax(160px,1fr)_1fr_1fr_1fr] border-b border-border bg-muted/20 px-4 py-2.5">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Token
              </span>
              {FRAMES.map((f) => (
                <button
                  key={f}
                  onClick={() => toggleSort(f)}
                  className={`flex items-center justify-center gap-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${
                    sortFrame === f ? "text-cyan font-semibold" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {f.toUpperCase()} Net Flow
                  {sortFrame === f && (
                    <span className="text-[8px]">{sortDir === "desc" ? "▼" : "▲"}</span>
                  )}
                </button>
              ))}
            </div>

            {/* Token rows */}
            <div className="divide-y divide-border/40">
              {sorted.map((token) => (
                <div
                  key={token.address}
                  className="grid grid-cols-[minmax(160px,1fr)_1fr_1fr_1fr] items-center gap-3 px-4 py-3 hover:bg-muted/10 transition-colors"
                >
                  {/* Token info */}
                  <Link
                    href={`/token/${token.address}`}
                    className="flex items-center gap-2.5 min-w-0 group"
                  >
                    {token.logo_uri ? (
                      <Image
                        src={token.logo_uri}
                        alt={token.symbol}
                        width={24}
                        height={24}
                        className="rounded-full shrink-0 ring-1 ring-border"
                        onError={(e) => {
                          (e.target as HTMLImageElement).style.display = "none";
                        }}
                      />
                    ) : (
                      <div className="h-6 w-6 rounded-full bg-muted shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="font-mono text-xs font-bold text-foreground group-hover:text-cyan transition-colors truncate">
                        {token.symbol || token.address.slice(0, 6)}
                      </p>
                      {token.name && (
                        <p className="font-mono text-[9px] text-muted-foreground truncate max-w-28">
                          {token.name}
                        </p>
                      )}
                    </div>
                  </Link>

                  {/* Flow cells */}
                  {FRAMES.map((f) => (
                    <FlowCell
                      key={f}
                      bucket={token[f]}
                      maxNet={maxNet}
                      address={token.address}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer note */}
        <p className="mt-4 font-mono text-[9px] text-muted-foreground/60 text-center">
          Data powered by Birdeye Smart Money endpoints · Cached 15 min · Click any token for full analysis
        </p>
      </main>
    </div>
  );
}
