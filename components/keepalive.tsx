"use client";

import { useEffect } from "react";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "https://zentryx-backend-cdf5.onrender.com";

export function Keepalive() {
  useEffect(() => {
    // Ping the backend every 10 minutes to prevent Render free-tier spindown
    const id = setInterval(() => {
      fetch(`${BACKEND_URL}/health`).catch(() => {});
    }, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  return null;
}
