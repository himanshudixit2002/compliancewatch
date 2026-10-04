import type { NextConfig } from "next";

// Static security headers; vercel.json carries the same set for the Vercel edge. Per-request
// values (the CSP nonce) are added by proxy.ts, not here.
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

// `make product` runs its own `next dev` beside a `make web-dev` of the same checkout. Next allows
// one dev server per build directory, so the product's builds into WEB_DIST_DIR (.next/product).
// It also answers on 127.0.0.1 as well as localhost: cookies ignore the port, so a session opened
// on localhost would be the other app's session too.
const productDistDir = process.env.WEB_DIST_DIR;

const nextConfig: NextConfig = {
  ...(productDistDir === undefined || productDistDir === ""
    ? {}
    : { distDir: productDistDir, allowedDevOrigins: ["127.0.0.1"] }),
  reactStrictMode: true,
  poweredByHeader: false,
  // The shared UI kit and the flag registry's client are consumed from TypeScript source
  // (packages/ui/src, packages/flags/src); Next compiles them.
  transpilePackages: ["@compliancewatch/ui", "@compliancewatch/flags"],
  // Links are checked against the route tree; registry links go through hrefFor().
  typedRoutes: true,
  // Linting is the separate `lint` turbo task: Next 16 removed `next lint` and the `eslint` option.
  // Type errors still fail `next build`.
  headers() {
    return Promise.resolve([{ source: "/(.*)", headers: SECURITY_HEADERS }]);
  },
};

export default nextConfig;
