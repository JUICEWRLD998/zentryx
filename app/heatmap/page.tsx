"use client";

import Link from "next/link";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface HeatmapData {
  tokens: { address: string; symbol: string }[];
  buckets: string[];
  cells: number[][];
  bucket_hours: number;
}

/** Map a net USD value to a Tailwind-style inline color */
function cellColor(value: number, maxAbs: number): string {
  if (maxAbs === 0 || Math.abs(value) < 0.5) return "rgba(30,30,58,0.6)";
  const intensity = Math.min(Math.log1p(Math.abs(value)) / Math.log1p(maxAbs), 1);
  if (value > 0) {
    // green: buy
    const g = Math.round(80 + intensity * 88); // 80–168
    return `rgba(0,${g},60,${0.3 + intensity * 0.65})`;
  } else {
    // red: sell
    const r = Math.round(140 + intensity * 80);
    return `rgba(${r},20,20,${0.3 + intensity * 0.65})`;
  }
}

function fmt_usd(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "+";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export default function HeatmapPage() {
  const router = useRouter();
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/heatmap`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setLastUpdated(new Date());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Compute max absolute value for color scaling
  const maxAbs =
    data && data.cells.length > 0
      ? Math.max(...data.cells.flat().map(Math.abs), 1)
      : 1;

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar activePage="heatmap" />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-6xl mx-auto w-full">
        {/* Header */}
        <div className="flex items-start justify-between mb-6 gap-4">
          <div>
            <h1 className="font-mono text-lg font-bold text-foreground tracking-widest mb-1">
              SMART MONEY HEATMAP
            </h1>
            <p className="font-mono text-xs text-muted-foreground">
              Net buy/sell flow per token · {data?.bucket_hours ?? 1}h buckets · green = net buy · red = net sell
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {lastUpdated && (
              <span className="font-mono text-xs text-muted-foreground hidden sm:block">
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={load}
              disabled={loading}
              className="font-mono text-xs border border-border rounded px-3 py-1.5 text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors disabled:opacity-40"
            >
              {loading ? "LOADING..." : "REFRESH"}
            </button>
          </div>
        </div>

        {error && (
          <div className="font-mono text-xs text-sell py-4">{error}</div>
        )}

        {!loading && data && data.tokens.length === 0 && (
          <div className="rounded-lg border border-border bg-card p-12 text-center">
            <p className="font-mono text-xs text-muted-foreground mb-2">NO TRADE DATA YET</p>
            <p className="font-mono text-xs text-muted-foreground/60">
              Trade events will appear here once tracked wallets are active.
            </p>
          </div>
        )}

        {data && data.tokens.length > 0 && (
          <div className="rounded-lg border border-border bg-card overflow-x-auto">
            <table className="w-full font-mono text-xs border-collapse min-w-[640px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-2.5 text-muted-foreground tracking-widest font-medium w-24 shrink-0">
                    TOKEN
                  </th>
                  {data.buckets.map((b, i) => (
                    <th key={i} className="text-center px-2 py-2.5 text-muted-foreground font-medium whitespace-nowrap">
                      {b}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.tokens.map((token, rowIdx) => (
                  <tr
                    key={token.address}
                    className="border-b border-border/40 last:border-0 group"
                  >
                    <td className="px-4 py-2 whitespace-nowrap">
                      <button
                        onClick={() => router.push(`/token/${token.address}`)}
                        className="text-foreground hover:text-buy transition-colors font-semibold tracking-wide group-hover:underline"
                      >
                        {token.symbol}
                      </button>
                    </td>
                    {data.cells[rowIdx].map((value, colIdx) => (
                      <td
                        key={colIdx}
                        title={`${token.symbol} @ ${data.buckets[colIdx]}: ${fmt_usd(value)}`}
                        className="px-1 py-1 text-center cursor-default"
                      >
                        <div
                          className="rounded text-center py-1.5 px-1 min-w-[52px] transition-all"
                          style={{ background: cellColor(value, maxAbs) }}
                        >
                          {Math.abs(value) >= 100 ? (
                            <span
                              className={
                                value > 0
                                  ? "text-buy font-semibold"
                                  : value < 0
                                  ? "text-sell font-semibold"
                                  : "text-muted-foreground"
                              }
                            >
                              {fmt_usd(value)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground/40">—</span>
                          )}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Legend */}
        {data && data.tokens.length > 0 && (
          <div className="flex items-center gap-4 mt-4 font-mono text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded" style={{ background: "rgba(0,140,80,0.8)" }} />
              <span>NET BUY</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded" style={{ background: "rgba(200,30,30,0.8)" }} />
              <span>NET SELL</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded" style={{ background: "rgba(30,30,58,0.6)" }} />
              <span>NEUTRAL / &lt;$0.50</span>
            </div>
            <span className="ml-auto">INTENSITY = LOG SCALE OF USD FLOW</span>
          </div>
        )}
      </main>
    </div>
  );
}
