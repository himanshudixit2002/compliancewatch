import type { NextConfig } from "next";

// Static security headers; vercel.json carries the same set for the Vercel edge. Per-request
// values (the CSP nonce) are added by proxy.ts, not here.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The shared UI kit is consumed from TypeScript source (packages/ui/src); Next compiles it.
  transpilePackages: ["@compliancewatch/ui"],
  // Links are checked against the route tree; registry links go through hrefFor().
  typedRoutes: true,
  // Linting is the separate `lint` turbo task: Next 16 removed `next lint` and the `eslint` option.
  // Type errors still fail `next build`.
  headers() {
    return Promise.resolve([{ source: "/(.*)", headers: SECURITY_HEADERS }]);
  },
};

export default nextConfig;
