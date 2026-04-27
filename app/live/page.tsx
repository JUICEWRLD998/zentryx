"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useWebSocket, type TradeEvent } from "@/lib/useWebSocket";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL
    ? `${process.env.NEXT_PUBLIC_WS_URL}/ws/feed`
    : "ws://localhost:8000/ws/feed";

function StatusDot({ status }: { status: string }) {
  const color =
    status === "connected"
      ? "bg-buy"
      : status === "connecting"
      ? "bg-yellow-400"
      : "bg-sell";
  return (
    <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${color} animate-pulse`} />
      {status.toUpperCase()}
    </span>
  );
}

function TradeCard({ event }: { event: TradeEvent }) {
  const isBuy = event.side === "BUY";
  const usd = event.usd_value
    ? `$${Number(event.usd_value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
    : "—";
  const symbol = event.symbol || event.token_address.slice(0, 8);
  const secScore = event.mini_report?.security_score;
  const secColor =
    secScore == null ? "text-muted-foreground" : secScore >= 70 ? "text-buy" : secScore >= 40 ? "text-yellow-400" : "text-sell";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.25 }}
      className="rounded-lg border border-border bg-card p-4 font-mono text-sm"
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

        {/* Right: security + smart money */}
        <div className="flex flex-col items-end gap-0.5 shrink-0">
          {secScore != null && (
            <span className={`text-xs ${secColor}`}>
              SEC {secScore.toFixed(0)}
            </span>
          )}
          {event.mini_report?.smart_money_flag && (
            <span className="text-xs text-cyan">◆ Smart $</span>
          )}
        </div>
      </div>

      {/* Token address */}
      <div className="mt-2 text-xs text-muted-foreground truncate">
        {event.token_address}
      </div>
    </motion.div>
  );
}

export default function LivePage() {
  const { events, status, clearEvents } = useWebSocket(WS_URL);

  return (
    <div className="flex flex-col flex-1 p-6 gap-6 max-w-3xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-lg font-semibold tracking-wider text-foreground">
            LIVE FEED
          </h1>
          <p className="font-mono text-xs text-muted-foreground mt-0.5">
            Real-time whale trades via Birdeye WebSocket
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
          <div className="rounded-lg border border-border bg-card p-8 text-center font-mono text-sm text-muted-foreground">
            {status === "connected"
              ? "Waiting for whale trades..."
              : "Connecting to live feed..."}
          </div>
        ) : (
          <AnimatePresence initial={false} mode="popLayout">
            {events.map((e, i) => (
              <TradeCard key={`${e.tx_hash ?? e.token_address}-${i}`} event={e} />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
