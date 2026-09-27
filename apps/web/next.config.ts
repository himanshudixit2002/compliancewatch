import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The shared UI kit is consumed from TypeScript source (packages/ui/src); Next compiles it.
  transpilePackages: ["@compliancewatch/ui"],
  // Linting is the separate `lint` turbo task: Next 16 removed `next lint` and the `eslint` option.
  // Type errors still fail `next build`.
};

export default nextConfig;
