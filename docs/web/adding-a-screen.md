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
  package) or `unscheduled(...)`. A route whose path comes from a design that is not a committed
  spec yet is awaited with `owner: "plan-k"` and `unconfirmed: true`; no entry awaits one today
  (the last ones moved to the services track's packages). A repository file it needs goes in
  `awaitsFiles`.
  A screen whose every route is already in a committed spec awaits nothing and is `ready`.
- `status`, which moves `planned`, then `waiting`, then `ready`, then `live`: `planned` when
  every awaited item is `unscheduled`; `waiting` when at least one awaited route or file is
  absent; `ready` when every awaited route and file is on `main` (each awaited route also under
  `uses`) and the screen is not built; `live` when the page exists and every `uses` route
  exists.
- `e2e`: the spec files under `apps/web/e2e` that visit a live page (empty otherwise).
- `guideRef`: the guide section (and an ADR or a guide table id where one applies).
- `nav: { group, order }` to show it in the shell (the groups are in `nav.ts`), `parent` for
  breadcrumbs, `notes` for a sentence the notice should show.

Then run `pnpm --filter web test`: `screens.test.ts` checks the entry against the specs and the
route tree, and `screens-doc.test.ts` fails until `pnpm --filter web screens:gen` has rewritten
`docs/web/screens.md`.

## 2. A screen that is not built

Stop after step 1. A planned, waiting or ready entry must not have a page file: `(app)/[...slug]`
or `admin/[...slug]` matches the path against the registry and renders `NotAvailableYet` with the
awaited routes, their owner and the guide reference, plus the `notes` sentence; for a ready entry
it says the backend is on main and the screen has not been built. A screen whose routes all
exist already is registered as `ready` with them under `uses`. Visit the route
to see it, regenerate `screens.md`, and open the pull request. If the notice should show data the
repository already has (a table generated from a YAML file, for example), register a component
under `features/not-available/ui/previews.tsx` and name it in `preview`.

## 3. A live screen

1. **Route file.** `src/app/<group>/<route>/page.tsx` under the right group: `(public)` for
   pages without a session, `(app)` for tenant screens, `admin/` for internal tools; a handler
   is `route.ts`. The page is thin: `metadata.title` from the registry entry (`screenById`), the
   gate on the first line, the read, and one feature view. The gate is
   `requireScreenSession(SCREEN)` for a tenant or account screen and `requireAdmin({ next })`
   under `/admin` ([auth-and-roles.md](auth-and-roles.md) lists every gate); a page that reads
   the session or a service exports `dynamic = "force-dynamic"`. `(app)/account/page.tsx` shows
   the shape (gate, then the view); a page that fetches gets a sibling `loading.tsx` with a
   `Skeleton`.
2. **Feature.** `src/features/<name>/` with `ui/` (the view components), `model/` (pure
   view-model helpers) and `index.ts`. A view takes plain props built by the page or a model
   function, uses `packages/ui` components and token classes only, has one h1 (`PageHeader`),
   gives every table a caption, says why an empty list is empty (`EmptyState`) and shows a
   failure with its correlation id (`ErrorState`). A feature that reads data adds `ports.ts`,
   `gateway.ts`, `queries.ts` and, for writes, `actions.ts` (the shape is in
   [data-layer.md](data-layer.md), "A feature that reads data"; `features/auth` has the first
   `actions.ts` and `queries.ts`). If `PARKED_FEATURES` in `src/test/architecture.ts` parks a
   folder for the screen, build on that folder rather than a new one: the page imports it, the
   data files join it, and its line leaves the map in the same change (the architecture test
   fails on a live screen whose parked folder no page imports, and on a map entry for a folder a
   page imports; [architecture.md](architecture.md), "Parked feature folders"). A new folder
   arrives with its page.
3. **Data.** Reads go through `queries.ts` and return a `Result`: the page renders the value,
   `EmptyState` with the reason for an empty list, or `ErrorState` from the error (title,
   detail, status, correlation id). A global read (plans, templates, rules, prompts, models)
   passes `cachedRead([tags.identity.plans()])` or its own tag, a tenant read `uncachedRead()`. A write is a server action
   in `actions.ts` that parses the form with zod, runs the gate again, calls the gateway, maps
   the `Result` with `toActionState`, and on success calls `afterMutation({ tags, paths })`
   before any `redirect`. Add a tag builder to `server/cache.ts` for a new cached record, and
   list a new creating write's natural key in [data-layer.md](data-layer.md).
4. **Strings.** Chrome text goes through `t("<feature>.<key>")` from `shared/i18n` with the key
   added to `messages/en.json`; the registry title is data and needs no key; enum values from a
   service go through `humanise()`. No regulatory fact is written into the app: it comes from
   service data, `docs/legal` or the ontology (`getOntology()`: questions, help lines and value
   labels from `GET /v1/ontology`). Every key in `en.json` is referenced in `src`: write the key
   out (`t("feature.key")` or a literal map of keys); a key built from a value with a template
   literal belongs to a dynamic family the i18n test lists with the module that builds it, so a
   new family is added there. A key nothing uses is deleted.
5. **Unit tests.** `<name>.test.tsx` beside every view with the axe assertion; `model/*.test.ts`
   for the helpers; gateway and action tests with `fakeFetch` from `src/test/fake-fetch.ts`
   asserting the method, path, headers and body of each call. The 80% floor holds per package.
   Test data is synthetic: "Example ..." text and dates in the year 2000; the guard in
   `src/test/synthetic-fixtures.test.ts` rejects realistic return, regulator, business and person
   names ([testing.md](testing.md), "Synthetic fixtures").
6. **End-to-end spec.** `apps/web/e2e/<name>.spec.ts` using the `test` from `./fixtures`: visit
   the route (after `await signIn(OWNER)` or another persona from the fixtures for a gated
   page), assert what the page shows, call `checkA11y()`. A page that reads a service runs
   against the real services with the seeded demo tenant (`make web-stack`, `make
   web-stack-wait`, `make web-seed`; the CI job runs them first), never a mock. Name the file
   in the entry's `e2e`; `a11y.spec.ts` already visits every registered page, so the spec
   covers behaviour, not the sweep. `admin-home.spec.ts` asserts one table per tool group and `sitemap.spec.ts` one
   per section, so a tool in a new navigation group changes that count.
7. **Registry.** `status: "live"`, `uses` complete, `e2e` filled, `notes` removed.
8. **Docs.** `pnpm --filter web screens:gen`; the feature's doc under `docs/web/` when the
   screen introduces behaviour worth a page; a `D-0NN` entry in `decisions.md` when a choice was
   made that later screens should follow.

## 4. When the backend lands: waiting to ready

When every awaited route and file of a waiting entry is on `main`, `screens.test.ts` fails with
`backend merged: flip <id> to ready (or live once built)`. That is the trigger; nothing flips by
itself. The change that sees the failure (often an unrelated UI change after a merge from
`main`) only moves the entry:

1. `make openapi-ts` if the spec is new or changed on the branch, so the generated types have
   the routes (`make openapi-ts-check` fails otherwise). A service's first spec also needs its
   name in `SERVICES_WITH_SPECS` (`shared/config/services.ts`) and a client factory in
   `server/api/services.ts` ([data-layer.md](data-layer.md)).
2. Add every landed awaited route to `uses` as well; keep it under `awaits` so the notice and
   `screens.md` still say who delivered it.
3. Set `status: "ready"`. Keep `preview` and `notes`.
4. `pnpm --filter web screens:gen`, then `pnpm --filter web test`.

The screen stays unbuilt in that change: the catch-all now says its backend is on main and it
has not been built yet. Building it is its own package (D-013 in [decisions.md](decisions.md)).

## 5. Building a ready screen: ready to live

1. Delete the landed routes from `awaits` (they are already under `uses`) and the landed files
   from `awaitsFiles`; a live screen may keep an await for an action it renders disabled, as
   long as that route is still absent.
2. Build the page, the feature and the tests as in section 3; add the e2e spec and list it. A
   parked folder for the screen is wired from the page and its line leaves `PARKED_FEATURES`.
3. Set `status: "live"` and delete `notes`.
4. `pnpm --filter web screens:gen`, then `pnpm --filter web test` and, with the stack up and
   seeded, `make web-e2e`.

A screen whose package is already building it when the backend lands may go straight from
waiting to live in that package's change.

`pnpm --filter web screens:audit` lists the awaited routes still absent from a committed spec,
marking the unconfirmed KAG-track paths, and then the ready entries with what each will use; a
route that landed under a different path shows up there as still absent and the registry entry
is corrected by hand.

## 6. Before the pull request

```bash
pnpm turbo run lint typecheck test build   # 80% floors in apps/web and packages/ui
pnpm format
env -i PATH="$PATH" HOME="$HOME" pnpm turbo run build --filter=web   # no CW_WEB_* needed
make check                                  # the gates CI runs, web-screens-check included
make web-stack && make web-stack-wait       # the services, as the CI e2e job starts them
make web-seed                               # the demo tenant and the recorded notification
make web-e2e                                # Playwright with axe against next start
make web-stack-down
```

Every commit is a one-line Conventional Commit subject without scope (`feat: web ...`,
`feat: ui ...`, `test: web ...`, `docs: web ...`); the pull request follows
`.github/PULL_REQUEST_TEMPLATE.md`.
