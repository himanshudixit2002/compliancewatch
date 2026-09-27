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
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/app/layout.tsx"],
      reporter: ["text", "lcov"],
      // No threshold yet: there is no domain code. Add `thresholds: { lines: 80 }` with the first feature.
    },
  },
});
