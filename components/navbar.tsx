"use client";

import Link from "next/link";
import Image from "next/image";
import { useState } from "react";
import { Menu, X, ArrowRight } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
} from "@/components/ui/sheet";

const TELEGRAM_BOT_URL = "https://t.me/zentryxtrade_bot";

type NavPage =
  | "leaderboard"
  | "live"
  | "movers"
  | "trades"
  | "trending"
  | "new-listings"
  | undefined;

const NAV_LINKS: { label: string; href: string; page: NavPage }[] = [
  { label: "LEADERBOARD", href: "/dashboard", page: "leaderboard" },
  { label: "LIVE FEED",   href: "/live",      page: "live" },
  { label: "MOVERS",      href: "/movers",    page: "movers" },
  { label: "TRADES",      href: "/trades",    page: "trades" },
  { label: "TRENDING",    href: "/trending",  page: "trending" },
  { label: "NEW LISTINGS", href: "/new-listings", page: "new-listings" },
];

interface NavBarProps {
  activePage?: NavPage;
  /** Show the "OPEN APP" CTA button (landing page only) */
  showCta?: boolean;
}

export function NavBar({ activePage, showCta = false }: NavBarProps) {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/80 backdrop-blur-sm px-4 sm:px-6 py-3 flex items-center justify-between">
      {/* ── Logo ── */}
      <Link href="/" className="flex items-center gap-2.5 group">
        <Image
          src="/zentryx-logo.png"
          alt="Zentryx"
          width={28}
          height={28}
          className="rounded-md"
          priority
        />
        <span className="font-mono text-sm font-semibold tracking-widest text-foreground group-hover:text-cyan transition-colors">
          ZENTRYX
        </span>
      </Link>

      {/* ── Desktop nav ── */}
      <nav className="hidden sm:flex items-center gap-5 font-mono text-xs text-muted-foreground">
        {NAV_LINKS.map(({ label, href, page }) =>
          page === activePage ? (
            <span key={href} className="text-foreground font-semibold">
              {label}
            </span>
          ) : (
            <Link key={href} href={href} className="hover:text-foreground transition-colors">
              {label}
            </Link>
          )
        )}
        <a
          href={TELEGRAM_BOT_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-foreground transition-colors"
        >
          BOT
        </a>
      </nav>

      {/* ── Right side: ThemeToggle + optional CTA + hamburger ── */}
      <div className="flex items-center gap-2">
        <ThemeToggle />

        {showCta && (
          <Link
            href="/dashboard"
            className="hidden sm:inline-flex items-center gap-1.5 rounded-md bg-buy text-primary-foreground font-mono text-xs font-semibold px-3 py-1.5 hover:opacity-90 transition-opacity"
          >
            OPEN APP <ArrowRight size={11} />
          </Link>
        )}

        {/* Hamburger — visible only below sm */}
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            className="sm:hidden flex items-center justify-center w-8 h-8 rounded-md border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
            aria-label="Open navigation menu"
          >
            {open ? <X size={16} /> : <Menu size={16} />}
          </SheetTrigger>

          <SheetContent side="left" showCloseButton={false} className="w-72 p-0">
            {/* Sheet header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
              <Link
                href="/"
                className="flex items-center gap-2"
                onClick={() => setOpen(false)}
              >
                <Image
                  src="/zentryx-logo.png"
                  alt="Zentryx"
                  width={24}
                  height={24}
                  className="rounded-sm"
                />
                <span className="font-mono text-sm font-semibold tracking-widest text-foreground">
                  ZENTRYX
                </span>
              </Link>
              <button
                onClick={() => setOpen(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Close menu"
              >
                <X size={16} />
              </button>
            </div>

            {/* Nav links */}
            <nav className="flex flex-col gap-0.5 px-3 py-4">
              {NAV_LINKS.map(({ label, href, page }) => (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setOpen(false)}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-md font-mono text-xs transition-colors ${
                    page === activePage
                      ? "bg-buy/10 text-buy font-semibold"
                      : "text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                  }`}
                >
                  {page === activePage ? (
                    <span className="h-1.5 w-1.5 rounded-full bg-buy shrink-0 animate-pulse" />
                  ) : (
                    <span className="h-1.5 w-1.5 shrink-0" />
                  )}
                  {label}
                </Link>
              ))}

              <div className="border-t border-border/60 mt-2 pt-2">
                <a
                  href={TELEGRAM_BOT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-md font-mono text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground transition-colors"
                >
                  BOT (TELEGRAM)
                </a>
              </div>
            </nav>

            {showCta && (
              <div className="px-5 py-4 border-t border-border/60 mt-auto">
                <Link
                  href="/dashboard"
                  onClick={() => setOpen(false)}
                  className="flex items-center justify-center gap-2 w-full rounded-lg bg-buy text-primary-foreground font-mono text-xs font-semibold px-4 py-3 hover:opacity-90 transition-opacity"
                >
                  OPEN APP <ArrowRight size={12} />
                </Link>
              </div>
            )}
          </SheetContent>
        </Sheet>
      </div>
    </header>
  );
}
