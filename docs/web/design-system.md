# Design system

`packages/ui` is the design system: the tokens, the primitives and the composites every screen
is built from. It has no build step; `apps/web` consumes the TypeScript source through the
package's `exports` map and Next's `transpilePackages`. Components come from this package only;
`apps/web/src/shared/ui` holds app-level compositions over them (the shells wired to
`next/link`, breadcrumbs, the status chip for a registry status) and never a second copy of a
primitive.

## Tokens

`src/styles/tokens.css` is imported by `apps/web/src/app/globals.css` after
`@import "tailwindcss"`; it never imports Tailwind itself. It has three parts.

**Colour roles.** Colours are roles, not hues, declared as CSS custom properties in hex:

| Role                             | Used for                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------- |
| `bg`, `surface`, `surface-raised`| The page, a panel on the page, a panel on a panel (cards, dialogs)                              |
| `fg`, `fg-muted`                 | Text, secondary text                                                                            |
| `line`, `line-strong`            | Dividers and borders; the stronger one for controls and anything that must be seen on its own   |
| `primary`, `accent`              | The action colour and the second accent, each with a `-fg` partner for text on top of it        |
| `success`, `warning`, `danger`, `info` | The tone colours with their `-fg` partners; the text carries the meaning, colour reinforces it |
| `focus`                          | The focus ring                                                                                  |
| `overlay`                        | The scrim behind a dialog or sheet                                                              |

Each role is declared once for the light scheme (`:root`) and once for the dark scheme, in two
places that must stay identical: `.dark` (forced dark) and `:root:not(.light)` under
`@media (prefers-color-scheme: dark)` (the OS decides unless `.light` forces light).
`src/tokens.test.ts` checks the two dark blocks agree.

**The Tailwind mapping.** An `@theme inline` block maps every role onto Tailwind's colour
namespace after removing the default palette (`--color-*: initial`), so the utilities are
`bg-bg`, `bg-surface`, `text-fg`, `text-fg-muted`, `border-line`, `ring-focus`, `bg-danger`,
`text-danger-fg` and so on, and `bg-red-500` or `text-white` do not exist. Opacity modifiers
work (`bg-fg/5` for a hover tint). In `apps/web` an eslint rule rejects a hex literal inside a
class string for the same reason: a colour that bypasses the roles bypasses the contrast test.

**Scales and base styles.** A plain `@theme` block declares the type scale (`text-xs` to
`text-3xl`, each with a line height), the radii (`rounded-sm`, `rounded-md`, `rounded-lg`), the
4px spacing base and the font stacks. Both stacks are system fonts (`ui-sans-serif, system-ui,
...`; `ui-monospace, ...`): no font file is downloaded at build time ([decisions.md](decisions.md)
D-009). Base styles set the body colours, make a bare `border` utility draw `line`, put a 2px
`focus` outline on `:focus-visible`, and shorten every animation and transition under
`prefers-reduced-motion`.

`src/tokens.ts` mirrors the names (`COLOR_TOKENS`, `TONES`, `TYPE_SCALE`, `RADII`) and parses
the scheme blocks back out of the CSS so tests check the file rather than a copy of it.
`src/styles/tokens.build.test.ts` compiles `tokens.css` with the real Tailwind engine and asserts
the utilities exist.

## Contrast

`src/contrast.ts` computes WCAG relative luminance and contrast ratios and lists the pairs the
tokens must satisfy: `TEXT_PAIRS` (text on a background: `fg` and `fg-muted` on `bg`, `surface`
and `surface-raised`; every `-fg` on its tone; every tone as text on `bg` and `surface`) and
`UI_PAIRS` (`line-strong` and `focus` against the backgrounds, the tones as UI colours).
`src/contrast.test.ts` reads `tokens.css` and fails when a text pair drops under 4.5:1 or a UI
pair under 3:1 in either scheme, naming the pair. Change a colour and this test says what broke.

## Components

Every component file exports the component and its props type, sets `data-slot` (and
`data-variant`, `data-tone`, `data-side` where it has one) for tests, and has a
`<name>.test.tsx` beside it that drives the keyboard behaviour with `@testing-library/user-event`
and ends with `expect(await runAxe(container)).toHaveNoViolations()`.

**Primitives** (generated with the shadcn CLI, then owned in place): Button (`primary`,
`secondary`, `ghost`, `danger`, `link`; `sm`, `md`, `lg`; a loading state with `aria-busy`;
`asChild` through the Radix Slot), Input, Label, Textarea, Checkbox, RadioGroup, Select (a styled
native `<select>`: the browser's listbox already gives keyboard and screen-reader support), Dialog
(focus trap, Escape, `aria-labelledby`), Sheet (a Dialog sliding in from a side; the mobile
navigation uses it), Tabs (the panel is focusable after the active trigger and shows the focus
ring), Table (semantic table primitives with a caption slot; `scrollLabel` makes the scroll
container of a table wider than its column a named, focusable region), Card, Badge,
Skeleton, Toaster (`sonner` with a polite live region; `toast` is re-exported).

**Composites**, each with its accessibility contract:

- `Field`: label, control, description and error; the control receives `id`,
  `aria-describedby`, `aria-invalid` and `aria-required`, and the error id is `<id>-error`.
- `CheckboxGroup`: a `<fieldset>` with the question as its `<legend>`, one labelled checkbox per
  option (Tab moves between boxes, Space toggles), an option's hint describing its box, the
  description and error describing the fieldset; every checked box submits `name=value`, so a
  server action reads `formData.getAll(name)`, and the value keeps the options' order.
- `NumberField`: a text input with `inputmode="numeric"` (or `decimal`) and the allowed range as
  a sentence in its description; a native number input changes its value on a scroll and reads
  out poorly. `DateField`: the browser's own date input with `min` and `max`; the value is
  always YYYY-MM-DD.
- `ProgressBar`: `role="progressbar"` named by its visible label, with `aria-valuenow`, the range
  and `aria-valuetext`, so a screen reader says "4 of 17 answered" rather than a percentage; the
  value is clamped and the track has a 3:1 border.
- `StatusChip`, `Badge`, `Banner`, `Timeline`: the `Tone` vocabulary (`neutral`, `success`,
  `warning`, `danger`, `info`); the text carries the meaning. A danger Banner is `role="alert"`,
  the other tones `role="status"`.
- `DraftBanner`: the fixed text "Draft - to be reviewed by a lawyer" with the document version.
- `EmptyState` (says why the list is empty), `ErrorState` (`role="alert"`; the problem title and
  detail; the correlation id in `<code>` with a `CopyButton`), `PageHeader` (the page's one h1,
  a description, a breadcrumbs slot and an actions slot), `Skeleton` inside `SkeletonGroup`
  (`role="status"` with a screen-reader "Loading", announced once per group).
- `AppShell` and `AdminShell`: a skip link to `<main id="main" tabIndex={-1}>`, the primary
  navigation (a Sheet under the `md` breakpoint), `aria-current="page"` on the active link, a
  user-menu slot, and a `Link` prop for the app's router link. `AdminShell` adds the grouped tool
  sidebar and an internal banner that names the environment.
- `KeyValue` (`<dl>` pairs, optional copy), `Timeline` (`<ol>` with `<time>`), `JsonView`
  (`<pre>` with a `<details>` per object or array), `Stepper` (`<ol>` with `aria-current="step"`
  and the text "Step 2 of 5").
- `ConfirmDialog` (says what the action records; a danger button when destructive; buttons
  disabled while pending) and `ReasonDialog` (adds a required reason; confirm stays disabled
  under ten characters; the error shows on blur; `onConfirm` receives the trimmed reason).
- `CitationCard`: the quote in `<blockquote>`, the clause reference, the document link, and a
  "Verified" chip or a "Not verified" warning; the quote is never paraphrased.
- `MonthCalendar`: `role="grid"`, weekday headers, one focusable cell at a time (roving
  tabindex), Arrow keys, Home, End, PageUp and PageDown (Shift for a year), Enter or Space to
  select, `aria-selected` and `aria-current="date"`, labelled month buttons, `renderDay` for
  per-day content, and a `timeZone` (default `Asia/Kolkata`) that only decides which day is today.
- `DataTable`: caption, `aria-sort` on sortable headers, sorting and paging either as callbacks
  for client components or as links (`sortHref`, `nextHref`, `prevHref`) for server-rendered
  pages, filter and empty slots; it never fetches.
- `NotAvailableYet`: the title, guide reference, roles and the awaited routes (method, path,
  owner), or one sentence saying no backend exists yet; with `backendReady`, a sentence saying
  the backend is on main and the screen has not been built, then the routes it will use.
- `CopyButton`, `VisuallyHidden`.

The `Tone` type, `humaniseStatus`, `describedBy` and `fieldIds` (for `aria-describedby`
wiring), `useControllableState` and the calendar date helpers (`dateKey`, `parseDateKey`,
`addDays`, `addMonths`, `daysInMonth`, `todayKey`) are exported alongside.

## How the primitives were generated

The shadcn CLI is not a dependency and never runs on CI. The primitives were generated once, in
`packages/ui`, with `components.json` (style `new-york`, `rsc`, `tsx`, the CSS file set to
`src/styles/tokens.css`, aliases onto `./src`):

```bash
cd packages/ui
pnpm dlx shadcn@4.21.0 add button input label textarea checkbox radio-group dialog sheet tabs table card badge skeleton sonner
```

The generated files were then edited and are owned in place: imports made relative
(`../lib/cn`, `./button`), every shadcn colour class replaced by a token class
(`bg-background` to `bg-bg`, `text-muted-foreground` to `text-fg-muted`, `border-input` to
`border-line-strong`, `destructive` to `danger`, hover tints as `bg-fg/5`), the
`tw-animate-css` classes dropped, `sonner.tsx` rewritten as `toaster.tsx` without `next-themes`,
and the two npm packages the CLI adds for those files (`cn`, `next-themes`) removed again.
`select.tsx` was written by hand as a native `<select>` instead of the Radix popover. The
runtime dependencies are `radix-ui`, `class-variance-authority`, `clsx`, `tailwind-merge`,
`lucide-react` and `sonner`, pinned exactly; none has an install script.

## Adding a component

1. Generate it with the CLI command above (or write it by hand next to the others).
2. Replace the shadcn classes with token classes; make the imports relative
   (`src/imports.test.ts` fails on a `@/` or a self-referencing package import).
3. Export the component and its props type from `src/index.ts`; set `data-slot`.
4. Write `<name>.test.tsx`: render, props, the keyboard behaviour with `user-event`, and the
   axe assertion. Coverage stays at the 80% floor.
5. Add it to the catalogue at `/design` (a section under
   `apps/web/src/features/design-catalogue/ui/sections/`) so it can be seen in both schemes.
6. Update the inventory above and `packages/ui/README.md`.

A composite name is fixed once it exists (`KeyValue`, not `DescriptionList`; `Banner`, not
`Callout`; `NotAvailableYet`, not `WaitingPage`); a new screen adds a component only when no
existing one covers it.

## The catalogue

`/design` renders every component in every state, grouped into nine sections (`tokens`,
`buttons`, `forms`, `feedback`, `surfaces`, `tables`, `calendar`, `content`, `states`), with a
control that forces `.light` or `.dark` on the root element or hands the choice back to the OS.
It exists only where `CW_WEB_ENV` is `local` or `test` (a 404 elsewhere) and replaces a
component workbench such as Storybook ([decisions.md](decisions.md) D-007). The Playwright suite
visits it, checks each section with axe, opens the dialogs and drives the calendar keys.

Its example data is obviously synthetic: the text is "Example clause text", the dates are in the
year 2000, identifiers are zeros. `fixtures.test.ts` and `catalogue.test.tsx` reject the
regulatory vocabulary (CBIC, GST, GSTR, GSTIN, section, rule, notification, act) in the fixtures
and on the rendered page, so nothing in the catalogue can be mistaken for real content.
