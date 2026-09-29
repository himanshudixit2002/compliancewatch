# Adding a screen

A screen is an entry in `apps/web/src/shared/config/screens.ts` before anything else exists. The
entry drives the navigation, the sitemap, the admin tool list, the "not available yet" page, the
accessibility sweep and the generated `screens.md`, so the first step is always the registry,
and the tests say what is missing after that.

## 1. Register it

Add an entry to `SCREEN_LIST`:

- `id`: `<section>.<name>` in dot notation (`owner.obligations`, `admin.review.task`); the
  section prefix must match `section`.
- `kind`: `page` for a screen with its own route, `handler` for a route handler, `component` or
  `capability` for something embedded in another page (its `route` is then the hosting page).
- `route`: Next segment syntax; parameters as `[businessId]`. A group page whose key contains
  slashes takes query parameters, not a path segment.
- `title`: English, shown as the page's h1, in links and in the docs.
- `roles`: the role ids that may open it, or `"public"`. Add `tenantKinds` when only some tenant
  kinds may, and `flag` when a feature flag hides it.
- `uses`: every service route the screen calls, as `uses(service, method, pathTemplate)`. Each
  must exist in a committed spec under `packages/contracts/openapi`; the test fails otherwise.
- `awaits`: every route it still needs, through `servicesTrack("WP<n>", ...)` (the delivering
  package), `kagTrack(...)` (path unconfirmed until that track's specs are committed) or
  `unscheduled(...)`. A repository file it needs goes in `awaitsFiles`.
- `status`: `live` when the page exists and every `uses` route exists; `waiting` when at least
  one awaited route or file is absent; `planned` when every awaited item is `unscheduled`.
- `e2e`: the spec files under `apps/web/e2e` that visit a live page (empty otherwise).
- `guideRef`: the guide section (and an ADR or a guide table id where one applies).
- `nav: { group, order }` to show it in the shell (the groups are in `nav.ts`), `parent` for
  breadcrumbs, `notes` for a sentence the notice should show.

Then run `pnpm --filter web test`: `screens.test.ts` checks the entry against the specs and the
route tree, and `screens-doc.test.ts` fails until `pnpm --filter web screens:gen` has rewritten
`docs/web/screens.md`.

## 2. A screen whose backend is absent

Stop after step 1. A waiting or planned entry must not have a page file: `(app)/[...slug]` or
`admin/[...slug]` matches the path against the registry and renders `NotAvailableYet` with the
awaited routes, their owner and the guide reference, plus the `notes` sentence. Visit the route
to see it, regenerate `screens.md`, and open the pull request. If the notice should show data the
repository already has (a table generated from a YAML file, for example), register a component
under `features/not-available/ui/previews.tsx` and name it in `preview`.

## 3. A live screen

1. **Route file.** `src/app/<group>/<route>/page.tsx` under the right group: `(public)` for
   pages without a session, `(app)` for tenant screens, `admin/` for internal tools; a handler
   is `route.ts`. The page is thin: `metadata.title` from the registry entry (`screenById`), the
   gate, the read, and one feature view. `/design` shows the shape today (an environment gate,
   then the view); a page that reads per-request state exports `dynamic = "force-dynamic"`.
2. **Feature.** `src/features/<name>/` with `ui/` (the view components), `model/` (pure
   view-model helpers) and `index.ts`. A view takes plain props built by the page or a model
   function, uses `packages/ui` components and token classes only, has one h1 (`PageHeader`),
   gives every table a caption, says why an empty list is empty (`EmptyState`) and shows a
   failure with its correlation id (`ErrorState`). A feature that reads data adds `ports.ts`,
   `gateway.ts`, `queries.ts` and, for writes, `actions.ts`; no feature on `main` has them yet,
   and the first one sets the shape the rest copy.
3. **Strings.** Chrome text goes through `t("<feature>.<key>")` from `shared/i18n` with the key
   added to `messages/en.json`; the registry title is data and needs no key; enum values from a
   service go through `humanise()`. No regulatory fact is written into the app: it comes from
   service data, `docs/legal` or the ontology file.
4. **Unit tests.** `<name>.test.tsx` beside every view with the axe assertion; `model/*.test.ts`
   for the helpers. The 80% floor holds per package.
5. **End-to-end spec.** `apps/web/e2e/<name>.spec.ts` using the `test` from `./fixtures`: visit
   the route, assert what the page shows, call `checkA11y()`. Name the file in the entry's
   `e2e`; `a11y.spec.ts` already visits every registered page, so the spec covers behaviour, not
   the sweep. `admin-home.spec.ts` asserts one table per tool group and `sitemap.spec.ts` one
   per section, so a tool in a new navigation group changes that count.
6. **Registry.** `status: "live"`, `uses` complete, `e2e` filled, `notes` removed.
7. **Docs.** `pnpm --filter web screens:gen`; the feature's doc under `docs/web/` when the
   screen introduces behaviour worth a page; a `D-0NN` entry in `decisions.md` when a choice was
   made that later screens should follow.

## 4. Flipping a waiting screen to live

When every awaited route of a waiting entry lands in a committed spec, `screens.test.ts` fails
with `backend merged: flip <id> to live`. That is the trigger; nothing flips by itself.

1. Move the landed routes from `awaits` to `uses` (a live screen may keep an await for an
   action it renders disabled, as long as that route is still absent).
2. Build the page, the feature and the tests as in section 3; add the e2e spec and list it.
3. Set `status: "live"` and delete `notes`.
4. `pnpm --filter web screens:gen`, then `pnpm --filter web test` and `make web-e2e`.

`pnpm --filter web screens:audit` lists the awaited routes still absent from a committed spec,
marking the unconfirmed KAG-track paths; a route that landed under a different path shows up
there as still absent and the registry entry is corrected by hand.

## 5. Before the pull request

```bash
pnpm turbo run lint typecheck test build   # 80% floors in apps/web and packages/ui
pnpm format
env -i PATH="$PATH" HOME="$HOME" pnpm turbo run build --filter=web   # no CW_WEB_* needed
make check                                  # the gates CI runs, web-screens-check included
make web-e2e                                # Playwright with axe against next start
```

Every commit is a one-line Conventional Commit subject without scope (`feat: web ...`,
`feat: ui ...`, `test: web ...`, `docs: web ...`); the pull request follows
`.github/PULL_REQUEST_TEMPLATE.md`.
