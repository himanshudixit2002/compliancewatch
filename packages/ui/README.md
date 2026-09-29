# ui package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 12, 13 and 15.

- **Owns:** The design system for the web app: colour, type, spacing and radius tokens with light and dark schemes, and the shared React components built on them
- **Owning team:** Core Product (guide section 14)
- **Consumes:** Tailwind v4 (the app imports it; this package only declares tokens and utilities on top of it)
- **Emits / publishes:** Consumed from source by apps/web through `exports` and Next's `transpilePackages`; no build step

## Layout

```
src/index.ts               # public exports
src/styles/tokens.css      # colour roles (:root, .dark, prefers-color-scheme), @theme mapping, type scale, radii, base styles
src/tokens.ts              # TypeScript mirror: token names, tone vocabulary, parser for the CSS blocks
src/contrast.ts            # WCAG luminance and contrast helpers, the text and UI pairs the tokens must satisfy
src/contrast.test.ts       # AA gate: 4.5:1 for every text pair, 3:1 for every UI pair, light and dark
src/styles/tokens.build.test.ts  # compiles tokens.css with the real Tailwind engine and checks the utilities
src/badge.tsx              # <Badge tone="neutral|success|warning|danger">
```

## Tokens

Colours are roles, not hues: `bg`, `surface`, `surface-raised`, `fg`, `fg-muted`, `line`,
`line-strong`, `primary`, `accent`, `success`, `warning`, `danger`, `info` (each tone with a
`-fg` partner for text on top of it) and `focus`. Each role is a CSS custom property declared
once for the light scheme and once for the dark scheme; `.dark` on the root forces dark,
`.light` forces light, and otherwise `prefers-color-scheme` decides.

`@theme inline` maps the roles onto Tailwind so components use `bg-bg`, `bg-surface`,
`text-fg`, `text-fg-muted`, `border-line`, `ring-focus`, `bg-danger`, `text-danger-fg` and so
on. The default Tailwind palette is removed, so `bg-red-500` and `text-white` do not exist:
every colour in a component goes through a role. Opacity modifiers still work (`bg-fg/5` for a
hover tint).

The type scale (`text-xs` to `text-3xl`, each with a line height), the radii (`rounded-sm`,
`rounded-md`, `rounded-lg`), the 4px spacing base and the system font stacks are a normal
`@theme` block. Base styles set the body colours, a 2px `--focus` outline on `:focus-visible`,
and respect `prefers-reduced-motion`.

`src/contrast.test.ts` reads `tokens.css` and fails when a text pair drops under 4.5:1 or a UI
pair under 3:1 in either scheme; change a colour and the test says which pair broke.

## How to run

`pnpm --filter @compliancewatch/ui test` (vitest + Testing Library, 80% coverage thresholds), `lint`, `typecheck`.
