import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// .mts on purpose: apps/web is not "type": "module", and this file uses import.meta.
export default defineConfig({
  plugins: [react()], // Next's tsconfig has jsx: "preserve"; the plugin forces the automatic runtime
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    // The seed's tests run under node (a file-level directive) over its helpers, its HTTP layer
    // with a recording fetch, its report and the recorded fixtures; its steps and entry point
    // talk to the running services and are exercised by make web-seed. The end-to-end guard's
    // decision is tested the same way; its entry point asks the running services.
    include: [
      "src/**/*.test.{ts,tsx}",
      "scripts/seed/*.test.mts",
      "scripts/stack-guard/*.test.mts",
    ],
    setupFiles: ["src/test/setup.ts"],
    // axe runs in jsdom take seconds on hosted CI runners (a month grid took 5.6 s there, over
    // the 5 s default), so tests get a wider ceiling; a real hang still fails.
    testTimeout: 30_000,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}", "scripts/seed/{lib,http,report}.mts"],
      // Route files are thin (gate, query, render) and are exercised by the Playwright suite;
      // the unit floor applies to features, entities, server and shared code.
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/test/setup.ts",
        "src/app/**/{page,layout,loading,error,not-found,global-error,template}.tsx",
        "src/app/**/route.ts",
        "src/instrumentation.ts",
        "src/proxy.ts",
        "src/shared/generated/**",
      ],
      reporter: ["text", "lcov"],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
});
