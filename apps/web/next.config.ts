import type { NextConfig } from "next";

// Static security headers; vercel.json carries all but Permissions-Policy for the Vercel edge. The
// Content-Security-Policy is not here: it carries a nonce made per request in src/proxy.ts, which
// a config header cannot; the stored-file handler sets a policy of its own on an HTML page it
// serves (server/bff/raw-document.ts).
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

// Next checks a server action's Origin against the request's Host. Behind Vercel's preview and
// production domains the two agree, but a deployment reached through another host name (a custom
// domain fronted by a proxy, a tunnel) names it here, comma separated, so its forms still post
// (`CW_WEB_ALLOWED_ORIGINS=app.example.com,*.example.com`; read at build time).
const allowedOrigins = (process.env.CW_WEB_ALLOWED_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter((origin) => origin !== "");

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
  ...(allowedOrigins.length === 0 ? {} : { experimental: { serverActions: { allowedOrigins } } }),
  headers() {
    return Promise.resolve([{ source: "/(.*)", headers: SECURITY_HEADERS }]);
  },
};

export default nextConfig;
