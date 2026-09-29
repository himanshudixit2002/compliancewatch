# ui package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 12, 13 and 15.

- **Owns:** The design system for the web app: colour, type, spacing and radius tokens with light and dark schemes, the shadcn-generated primitives owned in place, and the composites built on them
- **Owning team:** Core Product (guide section 14)
- **Consumes:** Tailwind v4 (the app imports it; this package only declares tokens and utilities on top of it)
- **Emits / publishes:** Consumed from source by apps/web through `exports` and Next's `transpilePackages`; no build step

## Layout

```
components.json            # shadcn CLI settings (style new-york, rsc, aliases onto ./src)
src/index.ts               # public exports
src/styles/tokens.css      # colour roles (:root, .dark, prefers-color-scheme), @theme mapping, type scale, radii, base styles
src/tokens.ts              # TypeScript mirror: token names, tone vocabulary, parser for the CSS blocks
src/contrast.ts            # WCAG luminance and contrast helpers, the text and UI pairs the tokens must satisfy
src/contrast.test.ts       # AA gate: 4.5:1 for every text pair, 3:1 for every UI pair, light and dark
src/styles/tokens.build.test.ts  # compiles tokens.css with the real Tailwind engine and checks the utilities
src/lib/cn.ts              # clsx + tailwind-merge
src/test/axe.ts            # runAxe() and the toHaveNoViolations matcher over axe-core (exported as ./test/axe)
src/test/setup.ts          # vitest setup: registers the matcher, cleans up after each test
src/imports.test.ts        # internal imports are relative, never "@/" or the package name
src/components/            # one file per component, <name>.test.tsx beside it
  button, input, textarea, label, checkbox, radio-group, select   # form controls
  dialog, sheet, tabs, table, card, badge, skeleton, toaster      # surfaces and feedback
```

## Components

The primitives were generated with the shadcn CLI and are owned in place; the CLI is not a
dependency and is never run on CI:

```bash
cd packages/ui
pnpm dlx shadcn@4.21.0 add button input label textarea checkbox radio-group dialog sheet tabs table card badge skeleton sonner
```

The generated files were then edited: imports made relative (`../lib/cn`, `./button`), every
shadcn colour class replaced by a token class (`bg-background` to `bg-bg`, `text-muted-foreground`
to `text-fg-muted`, `border-input` to `border-line-strong`, `destructive` to `danger`, hover
tints as `bg-fg/5`), the `tw-animate-css` classes dropped, `sonner.tsx` rewritten as
`toaster.tsx` without `next-themes` (the toasts read the tokens through sonner's CSS variables),
and the two npm packages the CLI adds for those files (`cn`, `next-themes`) removed again.
`select.tsx` is a styled native `<select>` rather than the Radix popover: the browser's own
listbox already gives keyboard and screen-reader support. `badge.tsx` keeps the `tone` API of
the original component.

Every component exports its props type, sets `data-slot` (and `data-variant`, `data-tone`,
`data-side` where it has one) for tests, and has a Testing Library test that drives the keyboard
behaviour with `@testing-library/user-event` and ends with
`expect(await runAxe(container)).toHaveNoViolations()`.

To add a component: generate it with the CLI command above (or write it by hand next to the
others), replace the shadcn classes with token classes, make the imports relative, export it
and its props type from `src/index.ts`, and add `<name>.test.tsx` with the axe assertion. The
coverage thresholds are 80% for lines, functions, branches and statements.

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
