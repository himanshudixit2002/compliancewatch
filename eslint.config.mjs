// Base ESLint 9 flat config for framework-less TypeScript packages (apps/whatsapp-bot, packages/ui).
// apps/web has its own eslint.config.mjs built on eslint-config-next, which bundles
// @typescript-eslint; it must not be registered a second time from here.
import { defineConfig, globalIgnores } from "eslint/config";
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier/flat";

export default defineConfig([
  globalIgnores([
    "**/node_modules/",
    "**/dist/",
    "**/.next/",
    "**/.turbo/",
    "**/coverage/",
    // ESLint 9 looks the config up from the cwd, so a root-level `eslint .` must not touch apps/web.
    "apps/web/",
  ]),
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  // Must stay last: disables every rule that fights prettier.
  prettier,
]);
