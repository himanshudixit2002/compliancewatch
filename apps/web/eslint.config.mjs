// Next.js 16 ships eslint-config-next as native flat config; no FlatCompat needed.
// Do not spread the root eslint.config.mjs here: it would register @typescript-eslint twice.
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import prettier from "eslint-config-prettier/flat";

// Colours come from the token classes in packages/ui (bg-bg, text-fg, border-line ...); a hex
// literal inside a class string bypasses the contrast test.
const HEX_IN_CLASS = "/#[0-9a-fA-F]{3,8}\\b/";
const hexRule = (selector) => ({
  selector,
  message: "Use a token class from @compliancewatch/ui instead of a hex colour.",
});

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
      "no-restricted-syntax": [
        "error",
        hexRule(`JSXAttribute[name.name='className'] Literal[value=${HEX_IN_CLASS}]`),
        hexRule(`JSXAttribute[name.name='className'] TemplateElement[value.raw=${HEX_IN_CLASS}]`),
        hexRule(`CallExpression[callee.name='cn'] Literal[value=${HEX_IN_CLASS}]`),
        hexRule(`CallExpression[callee.name='cn'] TemplateElement[value.raw=${HEX_IN_CLASS}]`),
      ],
    },
  },
  prettier,
  globalIgnores([".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts"]),
]);
