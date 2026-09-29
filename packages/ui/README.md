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
src/lib/ids.ts             # describedBy() and fieldIds() for aria-describedby wiring
src/hooks/use-controllable-state.ts  # controlled-or-uncontrolled state for composites
src/components/            # one file per component, <name>.test.tsx beside it
  button, input, textarea, label, checkbox, radio-group, select   # form controls (shadcn)
  dialog, sheet, tabs, table, card, badge, skeleton, toaster      # surfaces and feedback (shadcn)
  field, status-chip, banner, draft-banner, empty-state, error-state, copy-button, visually-hidden
  page-header, app-shell, admin-shell, key-value, timeline, json-view, stepper
  confirm-dialog, reason-dialog, citation-card, month-calendar, data-table, not-available-yet
  checkbox-group, number-field, date-field                         # composite form fields
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
the original component. `Table` takes `scrollLabel` for a table that can be wider than its
column: the scroll container becomes a named, focusable region, so a keyboard user can scroll it.

Every component exports its props type, sets `data-slot` (and `data-variant`, `data-tone`,
`data-side` where it has one) for tests, and has a Testing Library test that drives the keyboard
behaviour with `@testing-library/user-event` and ends with
`expect(await runAxe(container)).toHaveNoViolations()`.

### Composites

Built on the primitives and the tokens; each has its accessibility contract in the file:

- `Field`: label, control, description and error; the control gets `id`, `aria-describedby`,
  `aria-invalid` and `aria-required`, and the error id is `<id>-error`.
- `CheckboxGroup`: a fieldset whose legend is the question, one labelled checkbox per option
  (Tab between boxes, Space toggles), every checked box submitting `name=value` so a server
  reads `formData.getAll(name)`; the value keeps the options' order; description and error
  describe the fieldset; controlled or uncontrolled.
- `NumberField`: a number typed as text (`inputmode` numeric or decimal, no scroll-to-change)
  with the range in words under it ("Between 0 and 1,00,000."); `DateField`: the browser's
  date input with `min` and `max`, always submitting YYYY-MM-DD. Both are wired through `Field`.
- `ProgressBar`: `role="progressbar"` named by its visible label, with `aria-valuenow`, the
  range and `aria-valuetext` ("4 of 17 answered" is read out, not a percentage); the value is
  clamped and the track has a 3:1 border.
- `StatusChip`, `Badge`, `Banner`, `Timeline`: the `Tone` vocabulary (neutral, success,
  warning, danger, info); the text carries the meaning, colour only reinforces it. A danger
  Banner is `role="alert"`, the other tones `role="status"`.
- `DraftBanner`: the fixed text "Draft - to be reviewed by a lawyer" with the document version.
- `EmptyState` (says why the list is empty), `ErrorState` (`role="alert"`, the problem title
  and detail, the correlation id in `<code>` with a `CopyButton`), `PageHeader` (the page's
  one h1), `Skeleton` inside `SkeletonGroup` (`role="status"` with a screen-reader "Loading").
- `AppShell` and `AdminShell`: skip link to `<main id="main">`, primary navigation (a Sheet
  under the md breakpoint), `aria-current="page"` on the active link, a `Link` prop for the
  app's router link. AdminShell adds the grouped tool sidebar and an internal banner naming
  the environment.
- `KeyValue` (`<dl>`), `Timeline` (`<ol>` with `<time>`), `JsonView` (`<pre>` with `<details>`
  per object or array), `Stepper` (`aria-current="step"`, "Step 2 of 5").
- `ConfirmDialog` (says what the action records; danger button when destructive; buttons
  disabled while pending) and `ReasonDialog` (adds a required reason; confirm stays disabled
  under ten characters; the error shows on blur; `onConfirm` receives the trimmed reason).
- `CitationCard`: the quote in `<blockquote>`, the clause reference, the document link, and
  either a "Verified" chip or a "Not verified" warning; the quote is never paraphrased.
- `MonthCalendar`: `role="grid"` with one focusable cell (roving tabindex), Arrow keys, Home,
  End, PageUp and PageDown (Shift for a year), Enter or Space to select, `aria-selected` and
  `aria-current="date"`, month buttons with labels, `renderDay` for per-day content, and a
  `timeZone` (default Asia/Kolkata) that only decides which day is today.
- `DataTable`: caption, `aria-sort` on sortable headers, sorting and paging as callbacks for
  client components or as links (`sortHref`, `nextHref`, `prevHref`) for server-rendered
  pages; it never fetches.
- `NotAvailableYet`: title, guide reference, roles and the awaited routes (method, path,
  owner), or a sentence saying no backend exists yet; `backendReady` says instead that the
  backend is on main and the screen has not been built, and lists the routes it will use.

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
