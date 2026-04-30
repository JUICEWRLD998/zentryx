"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Zap,
  TrendingUp,
  Bell,
  BarChart3,
  Eye,
  ShieldCheck,
  Bot,
  ArrowRight,
  Activity,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TELEGRAM_BOT_URL = "https://t.me/zentryxtrade_bot";

interface Stats {
  whales: number;
  totalPnl: number;
  bestWinRate: number;
}

function fmt_usd(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

const FEATURES = [
  {
    icon: Activity,
    title: "Live Trade Feed",
    description:
      "Watch whale trades hit the blockchain in real time. Every $2,000+ move surfaces instantly in the live feed.",
    href: "/live",
    cta: "Open Feed →",
    accent: "text-buy",
    border: "hover:border-buy/40",
  },
  {
    icon: Eye,
    title: "Whale Profiles",
    description:
      "Deep-dive into any tracked wallet. PnL history, win rate analysis, token exposure, and trade patterns — all in one view.",
    href: "/dashboard",
    cta: "View Leaderboard →",
    accent: "text-cyan",
    border: "hover:border-cyan/40",
  },
  {
    icon: ShieldCheck,
    title: "Token Intelligence",
    description:
      "Before copying a trade, check the token. Security score, honeypot detection, smart money signals, and liquidity data.",
    href: "/live",
    cta: "Explore Tokens →",
    accent: "text-yellow-400",
    border: "hover:border-yellow-400/40",
  },
  {
    icon: Bot,
    title: "Telegram Alerts",
    description:
      "Get instant notifications when a whale moves. Use /stats, /top, /filter, and /wallet commands to query live data from anywhere.",
    href: TELEGRAM_BOT_URL,
    cta: "Open Bot →",
    accent: "text-violet-400",
    border: "hover:border-violet-400/40",
    external: true,
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    icon: TrendingUp,
    title: "AI Discovers Top Wallets",
    body: "Zentryx scans Solana's weekly top performers using on-chain PnL and win-rate data, automatically selecting the wallets that consistently beat the market.",
    accent: "text-buy",
  },
  {
    step: "02",
    icon: Zap,
    title: "Signals Fire in Real Time",
    body: "When a tracked whale makes a large trade, Zentryx enriches it with token security data, smart money flags, and momentum metrics — then surfaces it instantly.",
    accent: "text-cyan",
  },
  {
    step: "03",
    icon: Bell,
    title: "You Copy With Confidence",
    body: "Act on intelligence, not noise. Every alert tells you who moved, what they bought, how much, and whether the token checks out — before you follow.",
    accent: "text-violet-400",
  },
];

function StatCard({
  label,
  value,
  color,
  loading,
}: {
  label: string;
  value: string;
  color: string;
  loading: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card/60 backdrop-blur px-6 py-5 text-center">
      <p className="font-mono text-xs text-muted-foreground tracking-widest mb-1">{label}</p>
      <p className={`font-mono text-3xl font-bold ${color} ${loading ? "animate-pulse" : ""}`}>
        {loading ? "—" : value}
      </p>
    </div>
  );
}

export default function Landing() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/wallets`)
      .then((r) => r.json())
      .then((data: { total_pnl: number; win_rate: number }[]) => {
        if (!Array.isArray(data) || data.length === 0) {
          setStats({ whales: 0, totalPnl: 0, bestWinRate: 0 });
          return;
        }
        setStats({
          whales: data.length,
          totalPnl: data.reduce((s, w) => s + w.total_pnl, 0),
          bestWinRate: Math.max(...data.map((w) => w.win_rate)),
        });
      })
      .catch(() => setStats({ whales: 0, totalPnl: 0, bestWinRate: 0 }))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Nav ── */}
      <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="h-2 w-2 rounded-full bg-buy animate-pulse" />
          <span className="font-mono text-sm font-semibold tracking-widest text-foreground">
            ZENTRYX
          </span>
        </div>
        <nav className="hidden md:flex items-center gap-6 font-mono text-xs text-muted-foreground">
          <Link href="/dashboard" className="hover:text-foreground transition-colors">DASHBOARD</Link>
          <Link href="/live" className="hover:text-foreground transition-colors">LIVE FEED</Link>
          <a
            href={TELEGRAM_BOT_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-foreground transition-colors"
          >
            BOT
          </a>
        </nav>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            href="/dashboard"
            className="hidden sm:inline-flex items-center gap-1.5 rounded-md bg-buy text-primary-foreground font-mono text-xs font-semibold px-3 py-1.5 hover:opacity-90 transition-opacity"
          >
            OPEN APP <ArrowRight size={11} />
          </Link>
        </div>
      </header>

      <main className="flex-1">
        {/* ── Hero ── */}
        <section className="relative overflow-hidden px-6 pt-24 pb-20 text-center">
          {/* Radial glow */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 flex items-start justify-center"
          >
            <div className="h-[500px] w-[700px] rounded-full bg-buy/10 blur-[120px] -translate-y-1/4 dark:bg-buy/8" />
          </div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="relative max-w-3xl mx-auto"
          >
            {/* Badge */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-buy/30 bg-buy/10 px-3 py-1 font-mono text-xs text-buy mb-6">
              <span className="h-1.5 w-1.5 rounded-full bg-buy animate-pulse" />
              LIVE ON SOLANA
            </span>

            <h1 className="font-mono text-4xl sm:text-6xl font-bold text-foreground leading-tight mb-4">
              Trade Like a{" "}
              <span className="text-buy">Whale.</span>
            </h1>

            <p className="text-muted-foreground text-lg sm:text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
              Zentryx is an AI-powered intelligence terminal that tracks Solana&apos;s top-performing
              wallets in real time — and alerts you the moment they move.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-lg bg-buy text-primary-foreground font-mono font-semibold text-sm px-6 py-3 hover:opacity-90 transition-opacity"
              >
                Open Dashboard <ArrowRight size={14} />
              </Link>
              <a
                href={TELEGRAM_BOT_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 rounded-lg border border-border font-mono font-semibold text-sm px-6 py-3 text-foreground hover:border-foreground/40 transition-colors"
              >
                <Bot size={14} /> Use Telegram Bot
              </a>
            </div>
          </motion.div>
        </section>

        {/* ── Live Stats Bar ── */}
        <section className="px-6 pb-20">
          <div className="max-w-3xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard
              label="WHALES TRACKED"
              value={stats ? stats.whales.toString() : "—"}
              color="text-cyan"
              loading={loading}
            />
            <StatCard
              label="TOTAL PNL (7D)"
              value={stats ? fmt_usd(stats.totalPnl) : "—"}
              color={stats && stats.totalPnl >= 0 ? "text-buy" : "text-sell"}
              loading={loading}
            />
            <StatCard
              label="BEST WIN RATE"
              value={stats ? `${(stats.bestWinRate * 100).toFixed(0)}%` : "—"}
              color="text-yellow-400"
              loading={loading}
            />
          </div>
        </section>

        {/* ── How It Works ── */}
        <section className="px-6 py-20 border-t border-border/50">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-14">
              <p className="font-mono text-xs text-muted-foreground tracking-widest mb-3">HOW IT WORKS</p>
              <h2 className="font-mono text-3xl font-bold text-foreground">
                From Discovery to Signal in{" "}
                <span className="text-buy">Seconds</span>
              </h2>
            </div>

            <div className="grid md:grid-cols-3 gap-6">
              {HOW_IT_WORKS.map(({ step, icon: Icon, title, body, accent }, i) => (
                <motion.div
                  key={step}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: i * 0.1 }}
                  className="rounded-xl border border-border bg-card p-6 flex flex-col gap-4"
                >
                  <div className="flex items-start justify-between">
                    <div className="rounded-lg border border-border bg-secondary p-2.5">
                      <Icon size={18} className={accent} />
                    </div>
                    <span className={`font-mono text-4xl font-bold ${accent} opacity-20 select-none`}>
                      {step}
                    </span>
                  </div>
                  <div>
                    <h3 className="font-mono font-semibold text-foreground mb-2">{title}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">{body}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Features ── */}
        <section className="px-6 py-20 border-t border-border/50">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-14">
              <p className="font-mono text-xs text-muted-foreground tracking-widest mb-3">PLATFORM</p>
              <h2 className="font-mono text-3xl font-bold text-foreground">
                Everything You Need to{" "}
                <span className="text-cyan">Copy Smarter</span>
              </h2>
            </div>

            <div className="grid sm:grid-cols-2 gap-5">
              {FEATURES.map(({ icon: Icon, title, description, href, cta, accent, border, external }, i) => (
                <motion.div
                  key={title}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: i * 0.08 }}
                >
                  {external ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`group block rounded-xl border border-border bg-card p-6 transition-colors ${border}`}
                    >
                      <FeatureCardContent Icon={Icon} title={title} description={description} cta={cta} accent={accent} />
                    </a>
                  ) : (
                    <Link
                      href={href}
                      className={`group block rounded-xl border border-border bg-card p-6 transition-colors ${border}`}
                    >
                      <FeatureCardContent Icon={Icon} title={title} description={description} cta={cta} accent={accent} />
                    </Link>
                  )}
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* ── CTA Banner ── */}
        <section className="px-6 py-20 border-t border-border/50">
          <div className="max-w-2xl mx-auto text-center">
            <div className="relative rounded-2xl border border-buy/20 bg-buy/5 dark:bg-buy/5 p-12 overflow-hidden">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 flex items-center justify-center"
              >
                <div className="h-[300px] w-[400px] rounded-full bg-buy/15 blur-[80px] dark:bg-buy/10" />
              </div>
              <div className="relative">
                <p className="font-mono text-xs text-buy tracking-widest mb-4">GET STARTED</p>
                <h2 className="font-mono text-3xl sm:text-4xl font-bold text-foreground mb-4">
                  Follow the Smart Money.
                </h2>
                <p className="text-muted-foreground mb-8 leading-relaxed">
                  The best traders don&apos;t guess — they follow wallets with proven track records.
                  Zentryx makes that intelligence available to everyone.
                </p>
                <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                  <Link
                    href="/dashboard"
                    className="inline-flex items-center gap-2 rounded-lg bg-buy text-primary-foreground font-mono font-semibold text-sm px-6 py-3 hover:opacity-90 transition-opacity"
                  >
                    Open Dashboard <ArrowRight size={14} />
                  </Link>
                  <Link
                    href="/live"
                    className="inline-flex items-center gap-2 rounded-lg border border-border font-mono font-semibold text-sm px-6 py-3 text-foreground hover:border-foreground/40 transition-colors"
                  >
                    <Activity size={14} /> Watch Live Feed
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-border px-6 py-8">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-buy" />
            <span className="font-mono text-xs font-semibold tracking-widest text-foreground">ZENTRYX</span>
          </div>
          <nav className="flex items-center gap-5 font-mono text-xs text-muted-foreground">
            <Link href="/dashboard" className="hover:text-foreground transition-colors">Dashboard</Link>
            <Link href="/live" className="hover:text-foreground transition-colors">Live Feed</Link>
            <a href={TELEGRAM_BOT_URL} target="_blank" rel="noopener noreferrer" className="hover:text-foreground transition-colors">Telegram Bot</a>
          </nav>
          <p className="font-mono text-xs text-muted-foreground">Built on Solana · {new Date().getFullYear()}</p>
        </div>
      </footer>
    </div>
  );
}

function FeatureCardContent({
  Icon,
  title,
  description,
  cta,
  accent,
}: {
  Icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  description: string;
  cta: string;
  accent: string;
}) {
  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="rounded-lg border border-border bg-secondary w-10 h-10 flex items-center justify-center">
        <Icon size={18} className={accent} />
      </div>
      <div className="flex-1">
        <h3 className="font-mono font-semibold text-foreground mb-2">{title}</h3>
        <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
      </div>
      <span className={`font-mono text-xs font-semibold ${accent} group-hover:underline`}>{cta}</span>
    </div>
  );
}


