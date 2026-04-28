"use client";

import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { useState, useEffect, useCallback } from "react";
import { useWebSocket, type TradeEvent } from "@/lib/useWebSocket";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL
  ? `${process.env.NEXT_PUBLIC_WS_URL}/ws/feed`
  : "ws://localhost:8000/ws/feed";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

type MiniReport = TradeEvent["mini_report"];

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(2)}`;
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  const color =
    status === "connected" ? "bg-buy" : status === "connecting" ? "bg-yellow-400" : "bg-sell";
  return (
    <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${color} animate-pulse`} />
      {status.toUpperCase()}
    </span>
  );
}

function ScoreBar({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="font-mono text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono text-xs font-semibold ${color}`}>{value}</span>
    </div>
  );
}

function TradeCard({
  event,
  onClick,
}: {
  event: TradeEvent;
  onClick: (e: TradeEvent) => void;
}) {
  const isBuy = event.side === "BUY";
  const usd = event.usd_value
    ? `$${Number(event.usd_value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
    : "—";
  const symbol = event.symbol || event.token_address.slice(0, 8);
  const secScore = event.mini_report?.security_score;
  const secColor =
    secScore == null
      ? "text-muted-foreground"
      : secScore >= 70
      ? "text-buy"
      : secScore >= 40
      ? "text-yellow-400"
      : "text-sell";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.22 }}
      onClick={() => onClick(event)}
      className="rounded-lg border border-border bg-card p-4 font-mono text-sm cursor-pointer hover:border-border/80 hover:bg-secondary/20 transition-colors"
    >
      <div className="flex items-center justify-between gap-4">
        {/* Left: wallet + token */}
        <div className="flex flex-col gap-0.5 min-w-0">
          <span className="text-muted-foreground text-xs truncate">{event.wallet_label}</span>
          <span className="font-semibold text-foreground">${symbol}</span>
        </div>

        {/* Middle: side pill + amount */}
        <div className="flex items-center gap-2">
          <span
            className={`rounded px-2 py-0.5 text-xs font-bold tracking-wider ${
              isBuy ? "bg-buy/15 text-buy" : "bg-sell/15 text-sell"
            }`}
          >
            {event.side}
          </span>
          <span className="text-foreground font-semibold">{usd}</span>
        </div>

        {/* Right: security + smart money + expand hint */}
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          {secScore != null && (
            <span className={`text-xs ${secColor}`}>SEC {secScore.toFixed(0)}</span>
          )}
          {event.mini_report?.smart_money_flag && (
            <span className="text-xs text-cyan">◆ Smart $</span>
          )}
          <span className="text-xs text-muted-foreground/50">DETAILS →</span>
        </div>
      </div>

      {/* Token address */}
      <div className="mt-2 text-xs text-muted-foreground truncate">
        {event.token_address}
      </div>
    </motion.div>
  );
}

// ── Slide-over panel ───────────────────────────────────────────────────────

function TokenSlideOver({
  open,
  onOpenChange,
  event,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  event: TradeEvent | null;
}) {
  const [report, setReport] = useState<MiniReport | null>(null);
  const [loading, setLoading] = useState(false);

  // Populate report: use event's embedded mini_report first, fetch if incomplete
  useEffect(() => {
    if (!event) { setReport(null); return; }

    const embedded = event.mini_report;
    const isUsable =
      embedded &&
      (embedded.security_score != null || embedded.symbol != null || embedded.price != null);

    if (isUsable) {
      setReport(embedded);
      return;
    }

    // Fallback: fetch from REST endpoint
    setLoading(true);
    fetch(`${API_BASE}/api/tokens/${event.token_address}/mini-report`)
      .then((r) => r.json())
      .then(setReport)
      .catch(() => setReport(embedded ?? null))
      .finally(() => setLoading(false));
  }, [event]);

  const isBuy = event?.side === "BUY";
  const symbol = report?.symbol || event?.symbol || event?.token_address?.slice(0, 8) || "—";
  const secScore = report?.security_score;
  const secColor =
    secScore == null ? "text-muted-foreground" : secScore >= 70 ? "text-buy" : secScore >= 40 ? "text-yellow-400" : "text-sell";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[420px] overflow-y-auto font-mono bg-card border-border">
        {!event ? null : (
          <>
            <SheetHeader className="pb-4 border-b border-border">
              <div className="flex items-center gap-3 mb-1">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-bold tracking-wider ${
                    isBuy ? "bg-buy/15 text-buy" : "bg-sell/15 text-sell"
                  }`}
                >
                  {event.side}
                </span>
                {report?.smart_money_flag && (
                  <span className="text-xs text-cyan">◆ SMART MONEY</span>
                )}
              </div>
              <SheetTitle className="font-mono text-base font-bold text-foreground">
                ${symbol}
              </SheetTitle>
              <SheetDescription className="font-mono text-xs text-muted-foreground break-all">
                {event.token_address}
              </SheetDescription>
              <div className="mt-2 flex items-center gap-3">
                <span className="text-xs text-muted-foreground">{event.wallet_label}</span>
                <span className="text-foreground font-semibold">
                  {fmtUsd(event.usd_value)}
                </span>
              </div>
            </SheetHeader>

            {loading ? (
              <div className="py-8 text-center text-xs text-muted-foreground animate-pulse">
                LOADING REPORT...
              </div>
            ) : (
              <div className="px-4 pt-4 flex flex-col gap-6">
                {/* Security */}
                <div>
                  <p className="text-xs text-muted-foreground tracking-widest mb-3">SECURITY</p>
                  <div className="rounded-lg border border-border bg-background/40 px-4 py-1">
                    <ScoreBar
                      label="SECURITY SCORE"
                      value={secScore != null ? `${secScore.toFixed(0)}/100` : "—"}
                      color={secColor}
                    />
                    <ScoreBar
                      label="HONEYPOT"
                      value={
                        report?.is_honeypot == null ? "—" : report.is_honeypot ? "YES ⚠" : "CLEAN"
                      }
                      color={report?.is_honeypot ? "text-sell" : "text-buy"}
                    />
                    <ScoreBar
                      label="SMART MONEY"
                      value={report?.smart_money_flag ? "YES" : "NO"}
                      color={report?.smart_money_flag ? "text-cyan" : "text-muted-foreground"}
                    />
                  </div>
                </div>

                {/* Market */}
                <div>
                  <p className="text-xs text-muted-foreground tracking-widest mb-3">MARKET</p>
                  <div className="rounded-lg border border-border bg-background/40 px-4 py-1">
                    <ScoreBar label="PRICE" value={report?.price != null ? `$${report.price.toPrecision(4)}` : "—"} color="text-foreground" />
                    <ScoreBar label="MARKET CAP" value={fmtUsd(report?.market_cap)} color="text-foreground" />
                    <ScoreBar label="24H VOLUME" value={fmtUsd(report?.volume_24h)} color="text-foreground" />
                    <ScoreBar
                      label="24H MOMENTUM"
                      value={
                        report?.momentum_24h != null
                          ? `${report.momentum_24h >= 0 ? "+" : ""}${report.momentum_24h.toFixed(2)}%`
                          : "—"
                      }
                      color={
                        report?.momentum_24h == null
                          ? "text-muted-foreground"
                          : report.momentum_24h >= 0
                          ? "text-buy"
                          : "text-sell"
                      }
                    />
                  </div>
                </div>

                {/* Liquidity & holders */}
                <div>
                  <p className="text-xs text-muted-foreground tracking-widest mb-3">LIQUIDITY & HOLDERS</p>
                  <div className="rounded-lg border border-border bg-background/40 px-4 py-1">
                    <ScoreBar label="TOTAL LIQUIDITY" value={fmtUsd(report?.total_liquidity_usd)} color="text-foreground" />
                    <ScoreBar label="HOLDER COUNT" value={fmtNum(report?.holder_count)} color="text-foreground" />
                    <ScoreBar
                      label="BUY/SELL RATIO"
                      value={report?.buy_sell_ratio != null ? fmtPct(report.buy_sell_ratio) : "—"}
                      color={
                        report?.buy_sell_ratio == null
                          ? "text-muted-foreground"
                          : report.buy_sell_ratio >= 0.55
                          ? "text-buy"
                          : report.buy_sell_ratio <= 0.45
                          ? "text-sell"
                          : "text-yellow-400"
                      }
                    />
                  </div>
                </div>

                {/* Links */}
                <div className="flex flex-wrap gap-3 pb-4">
                  <a
                    href={`https://solscan.io/token/${event.token_address}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-cyan transition-colors border border-border rounded px-3 py-2"
                  >
                    SOLSCAN →
                  </a>
                  <Link
                    href={`/token/${event.token_address}`}
                    onClick={() => onOpenChange(false)}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors border border-border rounded px-3 py-2"
                  >
                    TOKEN DETAIL →
                  </Link>
                  {event.wallet_address && (
                    <Link
                      href={`/wallet/${event.wallet_address}`}
                      onClick={() => onOpenChange(false)}
                      className="text-xs text-muted-foreground hover:text-buy transition-colors border border-border rounded px-3 py-2"
                    >
                      WALLET DETAIL →
                    </Link>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function LivePage() {
  const { events, status, clearEvents } = useWebSocket(WS_URL);
  const [selected, setSelected] = useState<TradeEvent | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const handleCardClick = useCallback((event: TradeEvent) => {
    setSelected(event);
    setSheetOpen(true);
  }, []);

  const handleSheetChange = useCallback((open: boolean) => {
    setSheetOpen(open);
    if (!open) setSelected(null);
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Nav */}
      <header className="border-b border-border px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
          <Link href="/" className="font-mono text-sm font-semibold tracking-widest text-foreground hover:text-buy transition-colors">
            ZENTRYX
          </Link>
        </div>
        <nav className="flex items-center gap-6 font-mono text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground transition-colors">LEADERBOARD</Link>
          <span className="text-foreground border-b border-buy pb-0.5">LIVE FEED</span>
        </nav>
      </header>

      <main className="flex-1 px-6 py-8 max-w-3xl mx-auto w-full">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="font-mono text-lg font-semibold tracking-wider text-foreground">
              LIVE FEED
            </h1>
            <p className="font-mono text-xs text-muted-foreground mt-0.5">
              Large trades polled from Birdeye · click a card for details
            </p>
          </div>
          <div className="flex items-center gap-4">
            <StatusDot status={status} />
            {events.length > 0 && (
              <button
                onClick={clearEvents}
                className="font-mono text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                CLEAR ({events.length})
              </button>
            )}
          </div>
        </div>

        {/* Feed */}
        <div className="flex flex-col gap-3">
          {events.length === 0 ? (
            <div className="rounded-lg border border-border bg-card p-10 text-center font-mono text-sm text-muted-foreground">
              {status === "connected"
                ? "Waiting for large trades ($5K+ on SOL, USDC, BONK, WIF, JUP, PYTH)..."
                : "Connecting to live feed..."}
            </div>
          ) : (
            <AnimatePresence initial={false} mode="popLayout">
              {events.map((e, i) => (
                <TradeCard
                  key={`${e.tx_hash ?? e.token_address}-${i}`}
                  event={e}
                  onClick={handleCardClick}
                />
              ))}
            </AnimatePresence>
          )}
        </div>
      </main>

      <TokenSlideOver
        open={sheetOpen}
        onOpenChange={handleSheetChange}
        event={selected}
      />
    </div>
  );
}
