"use client";

import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type TradeStatus = "open" | "closed" | "cancelled";
type CloseReason = "tp" | "sl" | "manual" | null;

interface PaperTrade {
  id: string;
  token_address: string;
  symbol: string | null;
  side: string;
  entry_price: number;
  entry_time: string;
  tp_pct: number | null;
  sl_pct: number | null;
  position_size_usd: number | null;
  status: TradeStatus;
  exit_price: number | null;
  exit_time: string | null;
  pnl_pct: number | null;
  close_reason: CloseReason;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 0.001) return n.toExponential(3);
  if (n < 1) return `$${n.toFixed(5)}`;
  if (n < 1000) return `$${n.toFixed(3)}`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function duration(start: string, end: string | null): string {
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  const ms = b - a;
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  return `${h}h ${m}m`;
}

function closeReasonBadge(reason: CloseReason): React.ReactNode {
  if (!reason) return null;
  const map: Record<string, { label: string; cls: string }> = {
    tp: { label: "TAKE-PROFIT", cls: "bg-buy/20 text-buy border border-buy/30" },
    sl: { label: "STOP-LOSS",   cls: "bg-sell/20 text-sell border border-sell/30" },
    manual: { label: "MANUAL",  cls: "bg-muted text-muted-foreground border border-border" },
  };
  const cfg = map[reason] ?? { label: reason.toUpperCase(), cls: "bg-muted text-muted-foreground" };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-mono font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

// ── Summary bar ────────────────────────────────────────────────────────────

function SummaryBar({ trades }: { trades: PaperTrade[] }) {
  const closed = trades.filter((t) => t.status === "closed");
  const open   = trades.filter((t) => t.status === "open");
  const wins   = closed.filter((t) => (t.pnl_pct ?? 0) > 0).length;
  const winRate = closed.length > 0 ? Math.round((wins / closed.length) * 100) : null;
  const avgPnl  = closed.length > 0
    ? closed.reduce((s, t) => s + (t.pnl_pct ?? 0), 0) / closed.length
    : null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      {[
        { label: "Total Trades",  value: trades.length.toString() },
        { label: "Open",          value: open.length.toString() },
        { label: "Win Rate",      value: winRate != null ? `${winRate}%` : "—" },
        { label: "Avg PnL",       value: avgPnl != null ? fmtPct(avgPnl) : "—",
          cls: avgPnl == null ? "" : avgPnl >= 0 ? "text-buy" : "text-sell" },
      ].map(({ label, value, cls = "" }) => (
        <div key={label} className="rounded-xl border border-border/50 bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
          <p className={`text-2xl font-bold font-mono ${cls}`}>{value}</p>
        </div>
      ))}
    </div>
  );
}

// ── Trade row ──────────────────────────────────────────────────────────────

function TradeRow({ trade }: { trade: PaperTrade }) {
  const pnl = trade.pnl_pct;
  const pnlCls = pnl == null ? "" : pnl >= 0 ? "text-buy" : "text-sell";
  const symbol = trade.symbol ?? trade.token_address.slice(0, 8);
  const tokenUrl = `/token/${trade.token_address}`;

  return (
    <tr className="border-b border-border/30 hover:bg-muted/30 transition-colors">
      {/* Token */}
      <td className="py-3 px-4">
        <Link href={tokenUrl} className="font-mono font-semibold text-cyan-400 hover:text-cyan-300">
          ${symbol}
        </Link>
        <p className="text-xs text-muted-foreground font-mono mt-0.5">
          {trade.token_address.slice(0, 12)}…
        </p>
      </td>

      {/* Entry */}
      <td className="py-3 px-4">
        <p className="font-mono text-sm">{fmtPrice(trade.entry_price)}</p>
        <p className="text-xs text-muted-foreground">{fmtDate(trade.entry_time)}</p>
      </td>

      {/* Exit / current */}
      <td className="py-3 px-4">
        {trade.status === "open" ? (
          <span className="text-xs text-yellow-400 font-semibold animate-pulse">OPEN</span>
        ) : (
          <>
            <p className="font-mono text-sm">{fmtPrice(trade.exit_price)}</p>
            <p className="text-xs text-muted-foreground">{fmtDate(trade.exit_time)}</p>
          </>
        )}
      </td>

      {/* PnL */}
      <td className={`py-3 px-4 font-mono font-bold text-sm ${pnlCls}`}>
        {trade.status === "open" ? "—" : fmtPct(pnl)}
      </td>

      {/* Duration */}
      <td className="py-3 px-4 text-xs text-muted-foreground font-mono">
        {duration(trade.entry_time, trade.exit_time)}
      </td>

      {/* TP / SL targets */}
      <td className="py-3 px-4 text-xs font-mono">
        {trade.tp_pct != null && (
          <span className="text-buy">TP {fmtPct(trade.tp_pct)}</span>
        )}
        {trade.tp_pct != null && trade.sl_pct != null && " / "}
        {trade.sl_pct != null && (
          <span className="text-sell">SL {fmtPct(trade.sl_pct)}</span>
        )}
        {trade.tp_pct == null && trade.sl_pct == null && "—"}
      </td>

      {/* Size */}
      <td className="py-3 px-4 text-xs font-mono text-muted-foreground">
        {fmtUsd(trade.position_size_usd)}
      </td>

      {/* Close reason */}
      <td className="py-3 px-4">
        {trade.status === "closed" ? closeReasonBadge(trade.close_reason) : null}
      </td>
    </tr>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function TradesPage() {
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"open" | "closed">("open");

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/trades`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTrades(Array.isArray(data) ? data : (data.trades ?? []));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    const id = setInterval(fetchTrades, 30_000);
    return () => clearInterval(id);
  }, [fetchTrades]);

  const visible = trades.filter((t) =>
    tab === "open" ? t.status === "open" : t.status !== "open"
  );

  return (
    <div className="min-h-screen bg-background text-foreground">
      <NavBar activePage="trades" />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Paper Trades</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Follow whale signals and track your simulated positions.{" "}
            <span className="text-cyan-400 font-mono">
              Open a trade via Telegram: /track [token] [tp%] [sl%]
            </span>
          </p>
        </div>

        {/* Summary */}
        {!loading && <SummaryBar trades={trades} />}

        {/* Tabs */}
        <div className="flex gap-1 mb-4 border-b border-border/50">
          {(["open", "closed"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-semibold uppercase tracking-wider transition-colors border-b-2 -mb-px ${
                tab === t
                  ? "border-cyan-400 text-cyan-400"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
              <span className="ml-1.5 text-xs font-mono opacity-60">
                ({trades.filter((tr) =>
                  t === "open" ? tr.status === "open" : tr.status !== "open"
                ).length})
              </span>
            </button>
          ))}
        </div>

        {/* Table */}
        {loading ? (
          <div className="text-center py-24 text-muted-foreground">Loading trades…</div>
        ) : error ? (
          <div className="text-center py-24 text-sell">
            Failed to load trades: {error}
          </div>
        ) : visible.length === 0 ? (
          <div className="text-center py-24 text-muted-foreground">
            {tab === "open" ? (
              <>
                <p className="text-lg font-semibold mb-2">No open trades</p>
                <p className="text-sm">
                  Use{" "}
                  <span className="font-mono text-cyan-400">/track [token] [tp%] [sl%]</span>{" "}
                  in Telegram to open a position when a whale signal fires.
                </p>
              </>
            ) : (
              <p className="text-lg font-semibold">No closed trades yet</p>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border/50">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="py-3 px-4 text-left">Token</th>
                  <th className="py-3 px-4 text-left">Entry</th>
                  <th className="py-3 px-4 text-left">Exit</th>
                  <th className="py-3 px-4 text-left">PnL</th>
                  <th className="py-3 px-4 text-left">Duration</th>
                  <th className="py-3 px-4 text-left">Targets</th>
                  <th className="py-3 px-4 text-left">Size</th>
                  <th className="py-3 px-4 text-left">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((trade) => (
                  <TradeRow key={trade.id} trade={trade} />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer note */}
        <p className="mt-6 text-xs text-muted-foreground text-center">
          Paper trades only — no real funds. Prices monitored every 2 minutes via Birdeye.
          Refreshes every 30 seconds.
        </p>
      </main>
    </div>
  );
}
