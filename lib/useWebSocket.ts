"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type TradeEvent = {
  type: string;
  wallet_address: string | null;
  wallet_label: string;
  token_address: string;
  symbol: string | null;
  side: "BUY" | "SELL";
  usd_value: number | null;
  tx_hash: string | null;
  block_time: number | null;
  mini_report: {
    token_address: string;
    security_score: number | null;
    is_honeypot: boolean | null;
    smart_money_flag: boolean;
    momentum_24h: number | null;
    holder_count: number | null;
    buy_sell_ratio: number | null;
    total_liquidity_usd: number | null;
    symbol: string | null;
    price: number | null;
    market_cap: number | null;
    volume_24h: number | null;
  };
};

type Status = "connecting" | "connected" | "disconnected" | "error";

const RECONNECT_DELAY_MS = 3000;
const MAX_EVENTS = 100;

export function useWebSocket(url: string) {
  const [events, setEvents] = useState<TradeEvent[]>([]);
  const [status, setStatus] = useState<Status>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus("connected");
    };

    ws.onmessage = (e) => {
      if (!mountedRef.current) return;
      try {
        const data: TradeEvent = JSON.parse(e.data);
        setEvents((prev) => [data, ...prev].slice(0, MAX_EVENTS));
      } catch {
        // ignore malformed messages
      }
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      setStatus("error");
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus("disconnected");
      // Auto-reconnect
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, RECONNECT_DELAY_MS);
    };
  }, [url]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const clearEvents = useCallback(() => setEvents([]), []);

  return { events, status, clearEvents };
}
