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
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    // axe runs in jsdom take seconds on hosted CI runners (a month grid took 5.6 s there, over
    // the 5 s default), so tests get a wider ceiling; a real hang still fails.
    testTimeout: 30_000,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
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
