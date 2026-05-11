import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      // Birdeye / DexScreener logo CDN
      { protocol: "https", hostname: "wsrv.nl" },
      // IPFS gateways used by token metadata
      { protocol: "https", hostname: "ipfs.io" },
      { protocol: "https", hostname: "cloudflare-ipfs.com" },
      // Birdeye direct CDN
      { protocol: "https", hostname: "*.birdeye.so" },
      { protocol: "https", hostname: "birdeye.so" },
      // Social media avatars used as token logos
      { protocol: "https", hostname: "pbs.twimg.com" },
      // Generic token logo CDNs
      { protocol: "https", hostname: "raw.githubusercontent.com" },
      { protocol: "https", hostname: "arweave.net" },
      { protocol: "https", hostname: "*.arweave.net" },
    ],
  },
};

export default nextConfig;
