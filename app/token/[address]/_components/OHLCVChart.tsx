"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
} from "lightweight-charts";
import type {
  CandlestickData,
  IChartApi,
  ISeriesApi,
  Time,
} from "lightweight-charts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Types ────────────────────────────────────────────────────────────────────

type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
type Timeframe = "1D" | "7D" | "30D";

const TIMEFRAMES: { label: string; value: Timeframe }[] = [
  { label: "1D",  value: "1D" },
  { label: "7D",  value: "7D" },
  { label: "30D", value: "30D" },
];

// ─── Formatting ───────────────────────────────────────────────────────────────

function fmtCompact(n: number): string {
  if (!isFinite(n)) return "0";
  if (n < 0.0001) return n.toExponential(3);
  if (n < 1) return n.toPrecision(5);
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

// ─── Component ────────────────────────────────────────────────────────────────

interface OHLCVChartProps { address: string; symbol: string }

export default function OHLCVChart({ address, symbol }: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tf, setTf] = useState<Timeframe>("7D");
  const [hovered, setHovered] = useState<CandlestickData | null>(null);

  // Build chart once on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0a0d17" },
        textColor: "#8ea0bb",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1a2238" },
        horzLines: { color: "#1a2238" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#2f4365", labelBackgroundColor: "#10203a" },
        horzLine: { color: "#2f4365", labelBackgroundColor: "#10203a" },
      },
      timeScale: {
        borderColor: "#1f2a44",
        timeVisible: false,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: "#1f2a44" },
      width: containerRef.current.clientWidth,
      height: 340,
      handleScroll: true,
      handleScale: true,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00A86B",
      downColor: "#DC2626",
      borderUpColor: "#00A86B",
      borderDownColor: "#DC2626",
      wickUpColor: "#00A86B",
      wickDownColor: "#DC2626",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData) {
        setHovered(null);
        return;
      }
      const candle = param.seriesData.get(series) as CandlestickData | undefined;
      setHovered(candle ?? null);
    });

    const ro = new ResizeObserver(() => {
      if (!containerRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Update timescale visibility when timeframe changes
  useEffect(() => {
    chartRef.current?.applyOptions({
      timeScale: {
        borderColor: "#1f2a44",
        timeVisible: tf === "1D",
        secondsVisible: false,
      },
    });
  }, [tf]);

  const fetchData = useCallback(async () => {
    if (!seriesRef.current) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/tokens/${address}/ohlcv?timeframe=${tf}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw = (await res.json()) as Array<Candle & { unixTime?: number }>;
      const candles: CandlestickData[] = (Array.isArray(raw) ? raw : [])
        .map((c) => ({
          time: (c.time ?? c.unixTime ?? 0) as Time,
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        }))
        .filter((c) => isFinite(c.open) && isFinite(c.high) && isFinite(c.low) && isFinite(c.close) && c.time)
        .sort((a, b) => Number(a.time) - Number(b.time));

      if (candles.length === 0) {
        setError("No chart data available yet.");
        seriesRef.current.setData([]);
        return;
      }

      seriesRef.current.setData(candles);
      chartRef.current?.timeScale().fitContent();
    } catch (e) {
      setError(String(e));
      seriesRef.current.setData([]);
    } finally {
      setLoading(false);
    }
  }, [address, tf]);

  useEffect(() => {
    const id = setTimeout(() => {
      void fetchData();
    }, 0);
    return () => clearTimeout(id);
  }, [fetchData]);

  const isUp = hovered ? hovered.close >= hovered.open : true;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-foreground">{symbol} / USD</span>
          {hovered && (
            <span className={`font-mono text-xs font-bold ${isUp ? "text-buy" : "text-sell"}`}>
              O:{fmtCompact(hovered.open)} H:{fmtCompact(hovered.high)} L:{fmtCompact(hovered.low)} C:{fmtCompact(hovered.close)}
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {TIMEFRAMES.map(({ label, value }) => (
            <button
              key={value}
              type="button"
              onClick={() => setTf(value)}
              className={[
                "rounded px-2 py-0.5 font-mono text-[11px] font-semibold transition-all",
                tf === value
                  ? "bg-cyan/20 text-cyan"
                  : "text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="relative">
        <div ref={containerRef} className="w-full" style={{ height: 340 }} />
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-card/80">
            <div className="flex flex-col items-center gap-2">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
              <span className="font-mono text-xs text-muted-foreground">Loading chart…</span>
            </div>
          </div>
        )}
        {!loading && error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="font-mono text-xs text-muted-foreground">{error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
