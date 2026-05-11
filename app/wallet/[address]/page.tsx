"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { NavBar } from "@/components/navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface WalletDetail {
  address: string;
  label: string;
  is_tracked: boolean;
  pnl: {
    realized_usd?: number;
    unrealized_usd?: number;
    total_usd?: number;
    win_rate?: number;
    total_trade?: number;
    total_win?: number;
    total_loss?: number;
  };
  net_worth: {
    total_usd?: number;
  };
}

interface PortfolioItem {
  address: string;
  symbol: string;
  name: string;
  logo_uri: string;
  amount: number;
  price_usd: number;
  usd_value: number;
  allocation_pct: number;
}

interface BalanceChange {
  address: string;
  change_24h_usd: number;
  change_7d_usd: number;
  change_24h_pct: number;
  change_7d_pct: number;
  current_usd: number;
}

interface NetWorthBreakdownItem {
  symbol: string;
  category: string;
  value_usd: number;
  allocation_pct: number;
  logo_uri: string;
}

interface NetWorthDetails {
  address: string;
  total_usd: number;
  categories: { category: string; value_usd: number }[];
  breakdown: NetWorthBreakdownItem[];
}

interface ActivityItem {
  signature: string;
  type: string;
  side: string;
  token_address: string;
  token_symbol: string;
  amount: number;
  value_usd: number;
  timestamp: number;
  status: string;
}

type WalletTab = "overview" | "portfolio" | "balance" | "net-worth" | "activity";

function fmt_usd(n: number | undefined | null): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

function StatCard({
  label,
  value,
  sub,
  color = "text-foreground",
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <p className="font-mono text-xs text-muted-foreground tracking-widest mb-2">{label}</p>
      <p className={`font-mono text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="font-mono text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

export default function WalletPage() {
  const { address } = useParams<{ address: string }>();
  const [data, setData] = useState<WalletDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<WalletTab>("overview");
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [portfolioAddress, setPortfolioAddress] = useState<string | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);

  // Phase 1 — new panel state
  const [balanceChange, setBalanceChange] = useState<BalanceChange | null>(null);
  const [netWorthDetails, setNetWorthDetails] = useState<NetWorthDetails | null>(null);
  const [activity, setActivity] = useState<ActivityItem[] | null>(null);
  const [panelLoading, setPanelLoading] = useState(false);

  useEffect(() => {
    if (!address) return;
    const load = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/wallets/${address}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setData(await res.json());
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [address]);

  useEffect(() => {
    if (!address) return;
    setPortfolio([]);
    setPortfolioAddress(null);
    setPortfolioError(null);
    setBalanceChange(null);
    setNetWorthDetails(null);
    setActivity(null);
  }, [address]);

  useEffect(() => {
    if (!address) return;
    if (tab === "balance" && !balanceChange) {
      setPanelLoading(true);
      fetch(`${API_BASE}/api/wallets/${address}/balance-change`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setBalanceChange(d))
        .catch(() => {})
        .finally(() => setPanelLoading(false));
    } else if (tab === "net-worth" && !netWorthDetails) {
      setPanelLoading(true);
      fetch(`${API_BASE}/api/wallets/${address}/net-worth-details`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setNetWorthDetails(d))
        .catch(() => {})
        .finally(() => setPanelLoading(false));
    } else if (tab === "activity" && !activity) {
      setPanelLoading(true);
      fetch(`${API_BASE}/api/wallets/${address}/activity?limit=20`)
        .then(r => r.ok ? r.json() : null)
        .then(d => setActivity(d))
        .catch(() => {})
        .finally(() => setPanelLoading(false));
    }
  }, [tab, address, balanceChange, netWorthDetails, activity]);

  useEffect(() => {
    if (tab !== "portfolio" || !address) return;
    if (portfolioAddress === address) return; // already loaded for this wallet
    const load = async () => {
      setPortfolioLoading(true);
      setPortfolioError(null);
      try {
        const res = await fetch(`${API_BASE}/api/wallets/${address}/portfolio`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setPortfolio(await res.json());
        setPortfolioAddress(address);
      } catch (e) {
        setPortfolioError(String(e));
      } finally {
        setPortfolioLoading(false);
      }
    };
    load();
  }, [tab, address, portfolioAddress]);

  const shortAddr = address
    ? `${address.slice(0, 6)}...${address.slice(-4)}`
    : "";

  return (
    <div className="min-h-screen flex flex-col">
      <NavBar />

      <main className="flex-1 px-4 sm:px-6 py-8 max-w-5xl mx-auto w-full">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground mb-6">
          <Link href="/" className="hover:text-foreground transition-colors">LEADERBOARD</Link>
          <span>/</span>
          <span className="text-foreground">{data?.label ?? shortAddr}</span>
        </div>

        {loading ? (
          <div className="text-center font-mono text-xs text-muted-foreground animate-pulse py-20">
            LOADING WALLET DATA...
          </div>
        ) : error ? (
          <div className="text-center font-mono text-xs text-sell py-20">{error}</div>
        ) : data ? (
          <>
            {/* Wallet header */}
            <div className="mb-8">
              <h1 className="font-mono text-xl font-bold text-foreground mb-1">
                {data.label}
              </h1>
              <p className="font-mono text-xs text-muted-foreground break-all">{address}</p>
              {data.is_tracked && (
                <span className="mt-2 inline-block rounded border border-buy/40 px-2 py-0.5 font-mono text-xs text-buy bg-buy/10">
                  TRACKED WHALE
                </span>
              )}
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="TOTAL PNL"
                value={fmt_usd(data.pnl.total_usd)}
                color={(data.pnl.total_usd ?? 0) >= 0 ? "text-buy" : "text-sell"}
              />
              <StatCard
                label="REALIZED PNL"
                value={fmt_usd(data.pnl.realized_usd)}
                color={(data.pnl.realized_usd ?? 0) >= 0 ? "text-buy" : "text-sell"}
              />
              <StatCard
                label="WIN RATE"
                value={
                  data.pnl.win_rate != null
                    ? `${(data.pnl.win_rate * 100).toFixed(1)}%`
                    : "—"
                }
                sub={
                  data.pnl.total_win != null && data.pnl.total_loss != null
                    ? `${data.pnl.total_win}W / ${data.pnl.total_loss}L`
                    : undefined
                }
                color={
                  (data.pnl.win_rate ?? 0) >= 0.6
                    ? "text-buy"
                    : (data.pnl.win_rate ?? 0) >= 0.4
                    ? "text-yellow-400"
                    : "text-sell"
                }
              />
              <StatCard
                label="TOTAL TRADES"
                value={data.pnl.total_trade?.toLocaleString() ?? "—"}
              />
            </div>

            {/* Net worth (if available) */}
            {data.net_worth.total_usd != null && (
              <div className="rounded-lg border border-border bg-card p-5 mb-8">
                <p className="font-mono text-xs text-muted-foreground tracking-widest mb-2">
                  CURRENT NET WORTH
                </p>
                <p className="font-mono text-2xl font-bold text-cyan">
                  {fmt_usd(data.net_worth.total_usd)}
                </p>
              </div>
            )}

            {/* Solscan link */}
            <div className="flex gap-4 mb-8">
              <a
                href={`https://solscan.io/account/${address}`}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs text-muted-foreground hover:text-cyan transition-colors border border-border rounded px-3 py-2"
              >
                VIEW ON SOLSCAN →
              </a>
            </div>

            {/* Tab switcher */}
            <div className="flex flex-wrap gap-1 rounded-xl border border-border bg-card p-1 mb-6">
              {([
                { id: "overview" as WalletTab,   label: "Overview" },
                { id: "portfolio" as WalletTab,  label: "Portfolio X-Ray" },
                { id: "balance" as WalletTab,    label: "Balance Change" },
                { id: "net-worth" as WalletTab,  label: "Net Worth" },
                { id: "activity" as WalletTab,   label: "Activity" },
              ]).map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`rounded-lg px-3 py-1.5 font-mono text-[11px] font-semibold transition-colors ${
                    tab === t.id
                      ? "bg-cyan/15 text-cyan"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {tab === "overview" && (
              <div className="font-mono text-xs text-muted-foreground">
                Performance stats shown above.
              </div>
            )}

            {tab === "portfolio" && (
              <PortfolioXRay
                items={portfolio}
                loading={portfolioLoading}
                error={portfolioError}
              />
            )}

            {/* ── Balance Change Panel ── */}
            {tab === "balance" && (
              <div>
                {panelLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
                  </div>
                ) : !balanceChange ? (
                  <p className="font-mono text-xs text-muted-foreground py-8 text-center">No balance change data available.</p>
                ) : (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div className={`rounded-lg border p-4 ${
                        balanceChange.change_24h_usd >= 0 ? "border-buy/20 bg-buy/5" : "border-sell/20 bg-sell/5"
                      }`}>
                        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">24H Change</p>
                        <p className={`font-mono text-2xl font-bold mt-1 ${
                          balanceChange.change_24h_usd >= 0 ? "text-buy" : "text-sell"
                        }`}>
                          {balanceChange.change_24h_usd >= 0 ? "+" : ""}{fmt_usd(balanceChange.change_24h_usd)}
                        </p>
                        <p className={`font-mono text-xs mt-1 ${
                          balanceChange.change_24h_pct >= 0 ? "text-buy" : "text-sell"
                        }`}>
                          {balanceChange.change_24h_pct >= 0 ? "+" : ""}{balanceChange.change_24h_pct.toFixed(2)}%
                        </p>
                      </div>
                      <div className={`rounded-lg border p-4 ${
                        balanceChange.change_7d_usd >= 0 ? "border-buy/20 bg-buy/5" : "border-sell/20 bg-sell/5"
                      }`}>
                        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">7D Change</p>
                        <p className={`font-mono text-2xl font-bold mt-1 ${
                          balanceChange.change_7d_usd >= 0 ? "text-buy" : "text-sell"
                        }`}>
                          {balanceChange.change_7d_usd >= 0 ? "+" : ""}{fmt_usd(balanceChange.change_7d_usd)}
                        </p>
                        <p className={`font-mono text-xs mt-1 ${
                          balanceChange.change_7d_pct >= 0 ? "text-buy" : "text-sell"
                        }`}>
                          {balanceChange.change_7d_pct >= 0 ? "+" : ""}{balanceChange.change_7d_pct.toFixed(2)}%
                        </p>
                      </div>
                    </div>
                    {balanceChange.current_usd > 0 && (
                      <div className="rounded-lg border border-border bg-card p-4">
                        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Current Portfolio Value</p>
                        <p className="font-mono text-xl font-bold text-cyan mt-1">{fmt_usd(balanceChange.current_usd)}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── Net Worth Details Panel ── */}
            {tab === "net-worth" && (
              <div>
                {panelLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
                  </div>
                ) : !netWorthDetails ? (
                  <p className="font-mono text-xs text-muted-foreground py-8 text-center">No net worth details available.</p>
                ) : (
                  <div className="space-y-4">
                    <div className="rounded-lg border border-border bg-muted/20 p-4 flex items-center justify-between">
                      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Total Net Worth</p>
                      <p className="font-mono text-xl font-bold text-cyan">{fmt_usd(netWorthDetails.total_usd)}</p>
                    </div>
                    {/* Category breakdown */}
                    {netWorthDetails.categories.length > 0 && (
                      <div>
                        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-2">By Category</p>
                        <div className="space-y-2">
                          {netWorthDetails.categories.map((cat) => (
                            <div key={cat.category} className="flex items-center gap-3">
                              <span className="w-20 shrink-0 font-mono text-[10px] capitalize text-muted-foreground">{cat.category}</span>
                              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-cyan/60"
                                  style={{ width: `${Math.min(100, (cat.value_usd / netWorthDetails.total_usd) * 100)}%` }}
                                />
                              </div>
                              <span className="w-20 shrink-0 text-right font-mono text-xs text-foreground">{fmt_usd(cat.value_usd)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Top holdings */}
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Top Holdings</p>
                      <div className="divide-y divide-border/50 rounded-xl border border-border bg-card overflow-hidden">
                        {netWorthDetails.breakdown.slice(0, 10).map((item, i) => (
                          <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                            <span className="w-5 shrink-0 font-mono text-[9px] text-muted-foreground">#{i + 1}</span>
                            <span className="flex-1 font-mono text-xs font-semibold text-foreground">{item.symbol}</span>
                            <span className="font-mono text-[9px] text-muted-foreground capitalize">{item.category}</span>
                            <span className="font-mono text-xs text-foreground">{fmt_usd(item.value_usd)}</span>
                            <span className="w-10 text-right font-mono text-[10px] text-cyan">{item.allocation_pct.toFixed(1)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Activity Timeline Panel ── */}
            {tab === "activity" && (
              <div>
                {panelLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-cyan border-t-transparent" />
                  </div>
                ) : !activity || activity.length === 0 ? (
                  <p className="font-mono text-xs text-muted-foreground py-8 text-center">No recent activity found.</p>
                ) : (
                  <div className="divide-y divide-border/50 rounded-xl border border-border bg-card overflow-hidden">
                    {activity.map((tx, i) => {
                      const isBuy = tx.side === "BUY" || tx.type?.toLowerCase() === "buy";
                      const isSell = tx.side === "SELL" || tx.type?.toLowerCase() === "sell";
                      const timeStr = tx.timestamp
                        ? new Date(tx.timestamp * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                        : "—";
                      return (
                        <div key={i} className="flex items-center gap-3 px-4 py-3">
                          <span className={`w-8 shrink-0 inline-flex items-center justify-center rounded font-mono text-[8px] font-bold ${
                            isBuy ? "bg-buy/15 text-buy" : isSell ? "bg-sell/15 text-sell" : "bg-muted text-muted-foreground"
                          }`}>
                            {isBuy ? "BUY" : isSell ? "SELL" : tx.type?.slice(0, 4).toUpperCase() || "TX"}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="font-mono text-xs font-semibold text-foreground truncate">
                              {tx.token_symbol || tx.token_address.slice(0, 8)}
                            </p>
                            <p className="font-mono text-[9px] text-muted-foreground">{timeStr}</p>
                          </div>
                          <div className="text-right shrink-0">
                            <p className="font-mono text-xs text-foreground">{fmt_usd(tx.value_usd)}</p>
                            {tx.signature && (
                              <a
                                href={`https://solscan.io/tx/${tx.signature}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-mono text-[9px] text-muted-foreground hover:text-cyan transition-colors"
                              >
                                {tx.signature.slice(0, 8)}…
                              </a>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        ) : null}
      </main>
    </div>
  );
}

// ── Portfolio X-Ray panel ───────────────────────────────────────────────────

function fmt_price(n: number): string {
  if (n >= 1) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (n >= 0.001) return `$${n.toFixed(4)}`;
  return `$${n.toExponential(2)}`;
}

function fmt_amount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function PortfolioXRay({
  items,
  loading,
  error,
}: {
  items: PortfolioItem[];
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="text-center font-mono text-xs text-muted-foreground animate-pulse py-12">
        LOADING PORTFOLIO...
      </div>
    );
  }
  if (error) {
    return <div className="font-mono text-xs text-sell py-6">{error}</div>;
  }
  if (items.length === 0) {
    return (
      <div className="font-mono text-xs text-muted-foreground py-12 text-center">
        NO HOLDINGS FOUND
      </div>
    );
  }

  const top5 = items.slice(0, 5);
  const chartData = top5.map((i) => ({ symbol: i.symbol, value: i.usd_value }));

  return (
    <div className="space-y-6">
      {/* Allocation bar chart */}
      <div>
        <p className="font-mono text-xs text-muted-foreground tracking-widest mb-3">TOP 5 BY VALUE</p>
        <div style={{ height: 160 }}>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16, top: 0, bottom: 0 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="symbol" tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, fill: "#60608A" }} width={56} />
              <Tooltip
                cursor={{ fill: "transparent" }}
                contentStyle={{ background: "#0A0A1A", border: "1px solid #1E1E3A", fontFamily: "JetBrains Mono, monospace", fontSize: 11 }}
                formatter={(value) => {
                  const amount = typeof value === "number" ? value : Number(value ?? 0);
                  return [`$${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, "Value"];
                }}
              />
              <Bar dataKey="value" radius={[0, 3, 3, 0]}>
                {chartData.map((_, i) => (
                  <Cell key={i} fill={i === 0 ? "#00A86B" : "#0891B2"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Holdings table */}
      <div>
        <p className="font-mono text-xs text-muted-foreground tracking-widest mb-3">ALL HOLDINGS</p>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground text-left">
                <th className="pb-2 pr-4">#</th>
                <th className="pb-2 pr-4">TOKEN</th>
                <th className="pb-2 pr-4 text-right">AMOUNT</th>
                <th className="pb-2 pr-4 text-right">PRICE</th>
                <th className="pb-2 pr-4 text-right">VALUE</th>
                <th className="pb-2">ALLOCATION</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <tr key={item.address} className="border-b border-border/40 hover:bg-card/60 transition-colors">
                  <td className="py-2.5 pr-4 text-muted-foreground">{idx + 1}</td>
                  <td className="py-2.5 pr-4">
                    <Link href={`/token/${item.address}`} className="flex items-center gap-2 hover:text-buy transition-colors">
                      {item.logo_uri && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={item.logo_uri} alt="" className="w-5 h-5 rounded-full shrink-0" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                      )}
                      <span className="text-foreground font-semibold">{item.symbol}</span>
                      {item.name && <span className="text-muted-foreground hidden sm:inline truncate max-w-30">{item.name}</span>}
                    </Link>
                  </td>
                  <td className="py-2.5 pr-4 text-right text-muted-foreground">{fmt_amount(item.amount)}</td>
                  <td className="py-2.5 pr-4 text-right text-muted-foreground">{fmt_price(item.price_usd)}</td>
                  <td className="py-2.5 pr-4 text-right text-foreground font-semibold">{fmt_usd(item.usd_value)}</td>
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-border rounded-full h-1.5 min-w-15">
                        <div
                          className="h-1.5 rounded-full bg-buy"
                          style={{ width: `${Math.min(item.allocation_pct, 100)}%` }}
                        />
                      </div>
                      <span className="text-muted-foreground w-10 text-right shrink-0">{item.allocation_pct}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
