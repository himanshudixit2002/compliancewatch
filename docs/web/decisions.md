# Decisions

Choices local to the web app, numbered `D-001` onward, newest last. Each entry records the
date, the context, the decision and its consequences. A choice that binds other parts of the
platform (how services are called, how a session is carried) is an ADR under `docs/adr/` and is
referenced from here rather than restated: ADR-019 (the browser never calls a service; every
call goes through the server layer, with an encrypted stateless session) is the first.

## D-001: The browser never calls a service

2026-09-29. Services have no CORS, the rulebook's writes need a shared token, and the tenant is
identified by a header today. Every service call goes through the Next.js server, and the app
has no `NEXT_PUBLIC_*` variable: no service URL and no token is compiled into a client bundle.
Consequences: pages read on the server and render; client components get plain props; the
server-side data layer is the only place a base URL or a token lives; `apps/web/.env.example`
holds server-read variables only. The cross-cutting form of this decision (the session cookie
and the header contract with the services) is ADR-019.

## D-002: shadcn primitives are generated once into `packages/ui` and owned

2026-09-29. A component library as a dependency would pin the app to its release cadence and its
colour system. The primitives were generated with the shadcn CLI (`shadcn@4.21.0`, the command
is in `design-system.md`), post-processed to relative imports and token classes, and are edited
in place; the CLI is not a dependency and never runs on CI. Consequences: `radix-ui` and five
small runtime dependencies, no build step, every component has its own test and its
accessibility contract in the file; upgrading shadcn means regenerating a file and re-applying
the post-processing, which the README records.

## D-003: The screen registry is data and drives navigation, docs and tests

2026-09-29. With about a hundred screens, most of them waiting for a backend, a hand-kept
navigation, a hand-kept sitemap and a hand-kept docs table would drift. `shared/config/screens.ts`
is one list; navigation, breadcrumbs, the home links, the sitemap, the admin tool list, the
not-available pages, the accessibility sweep and `screens.md` read it, and `screens.test.ts`
checks it against the route tree and the committed OpenAPI specs. Consequences: a screen exists
in the registry before its files; a landed backend fails a test ("backend merged: flip") rather
than going unnoticed; the generated doc is the canonical screen list; the config files use
explicit `.ts` imports so plain Node can load them.

## D-004: No `cacheComponents`

2026-09-29. Next 16's `cacheComponents` mode is opt-in and changes what a page may read during
render. Every tenant screen reads a cookie and is dynamic by nature, and the few global reads
(plans, templates, rules) fit fetch-level revalidation with tags. The option stays off;
authenticated pages export `dynamic = "force-dynamic"` explicitly when they arrive.
Consequences: the caching model is fetch options and `revalidatePath`/`updateTag` in actions;
`/design` and the admin layout are already `force-dynamic` because they read `CW_WEB_ENV`.

## D-005: No `authInterrupts`

2026-09-29. `forbidden()` and `unauthorized()` are experimental in 16.3.6. A failed gate calls
`notFound()` under `/admin` (a non-regulatory role must not learn that a tool exists) or
redirects to `/forbidden` elsewhere. Consequences: `/forbidden` is a public page with a way out
(home, sign in with another account); the not-found page brings its own shell because it renders
below the root layout.

## D-006: English only, with a translator that can take Hindi

2026-09-29. No i18n framework: `en.json` is a flat typed table, `t()` interpolates `{name}`,
and `createTranslator("hi")` falls back key by key to English until `hi.json` exists. Screen
titles and navigation labels are registry data, not keys, because the config files must load
under plain Node. Consequences: a test scans `src` for `t()` literals; enum values are
humanised, not translated per value; date and money wording goes through the helpers in
`shared/lib`; the Hindi file, when written, is checked against the English key set.

## D-007: A catalogue page instead of Storybook

2026-09-29. A component workbench would add a second build, its own dependencies and a second
place to keep in step with the tokens. `/design` renders every component in every state inside
the real app, with a control that forces light or dark, and exists only where `CW_WEB_ENV` is
`local` or `test`. Consequences: the Playwright suite checks the catalogue section by section
with axe; the example data is synthetic by construction and a test rejects the regulatory
vocabulary in it; a new component is added to the catalogue in the same change.

## D-008: Two catch-all routes render every waiting and planned screen

2026-09-29. A three-line `page.tsx` per waiting screen would be about forty near-empty files
that drift from the registry. `(app)/[...slug]` and `admin/[...slug]` match the pathname against
the registry and render `NotAvailableYet` with the awaited routes, their owner and the guide
reference; a waiting or planned entry must not have a page file (the test fails if one
appears), and an unknown path is a real 404. Consequences: there is no `loading.tsx` above the
catch-alls (a loading boundary above `notFound()` streams a 200), so a later page that fetches
adds `loading.tsx` beside itself; the notice never shows sample data.

## D-009: System font stacks, no font download at build

2026-09-29. `next/font` fetches font files at build time, which needs network on every build
and adds a failure mode for nothing the product needs. The token file declares
`ui-sans-serif, system-ui, ...` and `ui-monospace, ...`; the contrast and type-scale tests do
not depend on a font. Consequences: builds are offline-safe; Devanagari text, when it comes,
renders in the system's font.

## D-010: The axe matcher is fifteen lines over `axe-core`

2026-09-29. `vitest-axe` has one release from 2022 with unverified typings against vitest 4;
`axe-core` was already in the lockfile through `eslint-config-next`. `packages/ui/src/test/axe.ts`
runs axe with the `region` and `color-contrast` rules off (a lone component has no landmarks;
jsdom cannot measure colour) and adds `toHaveNoViolations` to `expect`; `apps/web` imports it
through the package's `./test/axe` export. Consequences: one matcher for both packages;
page-level colour and landmark checks belong to the Playwright suite and the contrast test.

## D-011: The e2e suite runs against `next start` and needs no service

2026-09-29. On `main` no page calls a service, so the suite builds the app, starts it with
`CW_WEB_ENV=test` and visits every registered page: live pages by their route, waiting and
planned ones through the catch-alls. Consequences: `make web-e2e` and the `web-e2e` CI job need
no container; the health handler is the readiness signal; a suite that needs services will
start them explicitly and seed through their HTTP APIs, never through a mock. The CI job does
that now (D-022).

## D-012: `CW_WEB_ENV` is read directly until a validated environment module exists

2026-09-29. Two callers need the environment name (the internal shell's label and the design
catalogue's gate) and nothing else is read from the environment yet. `server/runtime.ts` reads
the one variable: unset means `local`, and an unknown value counts as `prod` so a typo never
opens a local-only page. Consequences: the build needs no `CW_WEB_*` variable (checked with an
empty environment); the validated, memoised environment module that arrives with the data layer
replaces this file's reader without changing its callers.

## D-013: A landed backend moves a screen to ready; building it is its own package

2026-09-29. The registry had three statuses, so a waiting entry whose backend landed on `main`
could only become `live`, and the "backend merged" failure asked for the whole screen inside
whatever change met it first. That happened when the flag registry (`packages/flags`) merged:
the flags console would have been built inside a CI fix. A fourth status, `ready`, sits between
`waiting` and `live`: every awaited route and file is on `main`, every awaited route is also
under `uses`, and there is no page file, so the catch-all serves the entry and says the backend
is on main and the screen has not been built. Consequences: the failure now reads
`backend merged: flip <id> to ready (or live once built)`; a UI change that meets it only moves
the entry to `ready` and regenerates `screens.md`; the screen is built, and set `live`, in the
package that owns it; `screens:audit` lists the ready entries; the status chip shows ready as
"Ready to build" in the `info` tone.

## D-014: A stateless, encrypted session cookie; no session table

2026-09-29. The app needs to know who is asking on every request, and the services will
verify a bearer token themselves once identity issues one. `cw_session` is a JWE
(`server/session.ts`: `dir` key management, A256GCM, the 32-byte `CW_WEB_SESSION_SECRET`)
holding `SessionClaims` (`entities/session/types.ts`: user, tenant, tenant kind, roles, display
name, second factor, session version, provider, issue and expiry, and the token fields the
identity work fills); httpOnly, SameSite=Lax, Secure outside local, path `/`, eight hours by
default. The browser holds ciphertext it cannot read; the server keeps no table.
Consequences: revocation is by expiry and by the session version identity keeps per user
(re-read in the proxy when `/me` exists); the secret is required only where a session is
encrypted or decrypted, so a build and the public pages need none; a cookie is written only in
a server action or a route handler, never during a render; the claims carry no personal data
beyond the display name. ADR-019 records the platform side of this choice.

## D-015: The proxy checks presence; the data access layer decides

2026-09-29. Next 16 runs `proxy.ts` before a route renders, on the Node runtime, but it is not
on the path of a server action and it must stay cheap. `src/proxy.ts` only sends a request for
a role-gated screen or for anything under `/admin` to `/sign-in?next=` when no `cw_session`
cookie exists; it does not decrypt. `server/dal.ts` is the authoritative gate: `verifySession`
decrypts once per request (React `cache`), `requireRole` redirects an anonymous visitor to
sign-in and a wrong role to `/forbidden`, `requireAdmin` answers 404 so a tenant role does not
learn that a tool exists, and `requireScreen` applies a registry entry's roles and tenant
kinds. Consequences: every page calls its gate on the first line and every action calls it
again; the proxy's public list is the registry (`roles: "public"`), so a new screen is gated
by its entry; `next` is honoured only as a same-origin path (`safeNext`); the redirect targets
come from the registry through `signInHref`, `forbiddenHref` and `homeFor` in
`shared/config/nav.ts`, which is why `/businesses` has a registry entry before its page
exists (ready: the business API is on `main`, and the list comes with the owner screens).

## D-016: One sign-in port; the fake adapter exists only in local and test

2026-09-29. The identity provider (ADR-014) and its routes are not on `main`, but every page
behind a role needs a session to be built and tested against. `server/auth/provider.ts`
declares the port (`startSignIn`, `completeSignIn`, `signOut`, the methods a provider offers)
and `providerFor(env)` picks the adapter named by `CW_WEB_AUTH_PROVIDER`; `server/auth/fake.ts`
is the only adapter today and mints a session for a chosen tenant (an existing id or a new
one), tenant kind, roles the kind allows and a display name, with the user id derived from the
tenant and the name so a returning name is the same user. The environment module refuses
`fake` unless `CW_WEB_ENV` is `local` or `test`, and the adapter's constructor refuses again;
`supabase` is a reserved value that answers "not available yet" until its adapter exists.
Consequences: the sign-in page, the action and the session module never name an adapter, so
the real one is a drop-in; the second factor a fake session asserts is documented as asserted,
not verified; the fake adapter keeps its name and file when the identity work replaces its body
with the dev provider tokens and the session exchange; failures are `Result` errors with
web-local problems, mapped to a form's `ActionState` like a service failure.

## D-017: Sign-out is a POST route handler; the sign-in form gets its action and options as props

2026-09-29. Two small choices the later screens copy. Sign-out is `POST /sign-out`
(`app/sign-out/route.ts`): the shells and the account page submit a plain form to it, so it
works without JavaScript, the handler expires the cookie on a relative redirect to
`/sign-in`, refuses a request from another site by `Sec-Fetch-Site` or by `Origin` against the
`Host` header (never against `request.nextUrl`, which `next start` builds from its bind
address), and any other method is a 405; there is no sign-out server action to keep in step. The sign-in form (`features/auth/ui/dev-sign-in-form.tsx`) is a
client component and the layer rule keeps client components to `shared`, `entities` and their
own directory, so the page passes it the `signIn` server action and the options the model built
(`signInFormOptions()`: the input names, the tenant kinds, the roles per kind) as props instead
of importing them. Consequences: a form's vocabulary lives in the feature's `model/` and is
unit-tested there; the client bundle carries no config module; the tenant shell's header shows
the business and account groups of the navigation for a session (settings pages stay reachable
from the sitemap until a settings menu exists).

## D-018: Global reads are cached by tag for five minutes; tenant reads are never cached

2026-09-29. Some records are the same for every tenant (billing plans, notification templates,
the rulebook's rules, documents and review queues, the gateway's prompts and models) and change
rarely; everything else is keyed by the session's tenant and must be current. `server/cache.ts`
builds the tags (`tags.identity.plans()`, `tags.rulebook.document(id)`, ...), `cachedRead(tags)`
gives a global read `next: { revalidate: 300, tags }`, `uncachedRead()` gives a tenant read
`cache: "no-store"`, and `afterMutation({ tags, paths })` in a server action expires the tags
with `updateTag` (read-your-writes) and refreshes the routes with `revalidatePath`. Authenticated
pages stay `force-dynamic`: Next honours an explicit `revalidate` on a fetch inside such a page
(only a fetch with no cache option is forced to no-store). Next keys a fetch cache entry on the
request headers too, so `server/api/client.ts` gives a cached read the request id `cached:<tags>`
instead of a fresh UUID; a cached read's correlation id therefore names the tags, not one
request. Consequences: no `cacheComponents`, no `"use cache"` and no `revalidateTag(tag, "max")`
on `main`; a screen that caches a read must name a tag the writing action expires; a read whose
call sends `Authorization` or `Cookie` is never cached by Next unless it carries an explicit
`revalidate`, which is the case for every `cachedRead`.

## D-019: Idempotency-Key only where a route requires it; natural keys make the other creating writes safe

2026-09-29. Two routes on `main` read an `Idempotency-Key`: the business API's `POST
/v1/businesses` and `POST /v1/businesses/{business_id}/registrations` require it, answer 428
(`idempotency-key-required`) without it, replay the first response for 24 hours, and answer 422
when a key comes back with a different body and 409 while the first request is still running
(py-common's idempotency module). Every other creating write the screens make is safe to repeat
without one: a profile registration is found by its GSTIN, an entity by its PAN and a location
by its label (a second POST returns the existing node with `created: false`); identity consents
are append-only and the state is the latest row; a rulebook document is keyed by its sha256
(201 created, 200 unchanged, 409 when the metadata differs) and its mentions and relation
candidates by the document and the extractor; a notification preference is a PUT by channel
and recipient. `server/api/idempotency.ts` holds the wiring: a page renders
`<IdempotencyKeyInput />` (one UUID per render of the form) and an action calls
`idempotencyHeaders(formData, operation)`, which answers the header only for an operation in
`IDEMPOTENT_ROUTES` (`profile.create-business`, `profile.add-registration`). Consequences: a
test holds that list to the committed specs both ways, so a route that starts requiring the
header fails the web tests until its operation is listed, and a listed route that stops
requiring it fails too; a 428 maps to its own `ApiError` kind, `precondition_required`, because
it means the web layer left the key out rather than the visitor sending something wrong; a form
value that is not a UUID is ignored, so the hidden field cannot inject a header.

## D-020: The local service stack for the web app runs on memory stores with fixed demo settings

2026-09-29. Every screen is built against real services, so the daily loop and the e2e job need
all ten of them running, and they must look the same on a fresh clone and on CI. `make
web-stack` starts each service the way `make run` does (uvicorn through `uv run --package`),
but all at once on `SERVICE_PORT_BASE`+1 to +10, with pids and logs under `var/web-stack`, and
with the stack's settings fixed in the recipe instead of inherited from `.env`: memory stores
for identity, profile, rulebook, obligation and the gateway ledger (no container), the
profile's built-in static GSTIN lookup (the demo GSTIN pre-fills), the billing provider `none`
(subscribe answers its honest 503), the publish flow and the KAG layer off, the inter-service
URLs on the same base, and the rulebook write token from `.env` or the placeholder
`local-write-token`. `STORE=postgres` is the persistent option on the compose Postgres.
Consequences: memory stores forget their rows when the stack stops, so `make web-seed` runs
after every `make web-stack`; a second working copy only moves `SERVICE_PORT_BASE`; the web
app's `CW_WEB_*_URL` defaults match the 8000 base; `make web-e2e` stays a build plus Playwright,
because no page on `main` calls a service yet, and a spec that needs one runs with the stack up.

## D-021: The seed replays the pipeline's recorded request bodies for one notification

2026-09-29. The admin review queues are empty on a fresh stack, and the web app must never
invent regulatory data. Running the pipeline needs a queue, a worker and a model; parsing the
PDF again in TypeScript would be a second parser that could disagree with the real one. The
seed therefore replays three committed JSON files, the exact bodies the pipeline's
`HttpRulebook` sends for notification 01/2026-Central Tax (document with clauses, mentions,
relation candidate), recorded once by `scripts/seed/fixtures/rulebook/record.py` with the
pipeline's `PdfParser`, mention grammar and relation stage over the PDF its own tests keep
(the candidate comes from the scripted answer the demo's knowledge-flow test uses; no model is
called). Before every run the seed hashes that PDF and refuses to continue unless the digest
and every span agree with the fixtures; the document id is the digest's first 32 hex digits
read as a UUID, the kernel's rule. Consequences: a change to the parser, the grammar, the relation stage or the PDF
means running the recorder again (the README has the `uv` command) and committing the new
files; the seed blanks the candidate's rule key when the target rulebook does not list that
rule, as the relation stage's answer schema would; the fixture test fails when the files drift.

## D-022: The e2e job starts the services and seeds them before Playwright

2026-09-29. The screens that follow read real services, and the seeded tenant is the data the
sign-in form already offers; a suite that only ever ran without the services would not notice
when the stack stopped starting or the seed stopped working. The `web-e2e` CI job installs uv
with Python 3.12 and the uv workspace, starts every service with `make web-stack` (memory
stores, no container), builds the app while they start, waits with `make web-stack-wait`,
runs `make web-seed`, and only then runs Playwright; it always prints the service log tails and
stops the stack, and uploads the logs and the seed state with the report on failure. Before
starting anything it also runs `make openapi-ts-check`, which no other job ran. Locally `make
web-e2e` stays a build plus Playwright, so the suite runs without Python; the one test that
needs the seed (the seeded-tenant sign-in) is skipped when `var/seed/last.json` is absent and
fails on CI instead. Consequences: the job takes the Python install time (cached by setup-uv);
a broken service start or seed fails the web gate; the job runs when either the `typescript`
or the `python` path filter matches, so a change to a service, to the Python packages the
services share, to `uv.lock` or `pyproject.toml`, to the Makefile's web-stack and seed recipes,
or to the recorded fixture the seed hashes is caught in its own pull request rather than by
the next unrelated web change; a later screen's spec may assume the seeded tenant and the
recorded notification exist.

## D-023: The web flags are entries in the shared flag registry

2026-09-29. The repository's flag registry (`packages/flags/registry.json`, checked by `make
flags-check`) arrived on `main` with an owner, a default, a removal condition and an expiry date
for every rollout switch, and a TypeScript SDK. The six `web.*` flags were declared as data in
`shared/config/flags.ts` until then; they are now registry entries (bool, off, `services:
["web"]`, expiring 2027-03-31 like the others) and `flags.ts` keeps only the typed list of names.
Each entry's `env` is `CW_WEB_FLAG_<NAME>`, the override variable the web app has always named,
so the SDK's env provider reads the same variable the docs promise. Consequences: `flags.test.ts`
fails when the name list and the registry's web entries differ; adding a web flag touches the
registry, py-common's generated copy (`make flags`) and `FLAG_NAMES`; the registry is a turbo
global dependency so a changed entry reruns the web tests; the reader, when a screen needs one,
reads through `@compliancewatch/flags/server` and honours the override only in local and test.

## D-024: The ontology comes from GET /v1/ontology, not from a generated module

2026-09-29. The screens need each attribute's question, help line, value labels, level, type and
source, and the operators per type. The first design generated a TypeScript module from
packages/ontology's YAML files with a drift check; since then the profile service serves exactly
that, worded, at `GET /v1/ontology` (with an ETag), and it is the source the services and the
rules use. `server/ontology.ts` reads it without a tenant header, caches it an hour under
`profile:ontology` (the service's own `max-age`), and `entities/ontology` maps it and holds the
lookups. Consequences: there is no generated file, no generator and no drift check; a wording
change reaches the screens within the hour of its release (or at once after
`updateTag(tags.profile.ontology())`); a page that needs the ontology fails with the service's
problem when the profile service is down, like any other read; unit tests use a synthetic body
(`src/test/ontology-fixture.ts`), never a copy of the real wording.

## D-025: The owner and CA screens use the business API; the node routes fill its gaps

2026-09-29. The first design built the owner screens on the profile node routes (register a
GSTIN, pre-fill, ask each node for its next question, write attributes per node). The business
API on `main` now does that as one resource: create a business from a GSTIN or a PAN (with the
pre-fill and the first question in the answer), read it with its registrations, store answers
across it in one all-or-nothing patch, and read the onboarding checklist with the question's
wording, options and progress. `features/business` builds on it, and calls the node routes only
for what it lacks: one node (locations, lineage parents), adding a location, the snapshot per
financial year and the review tasks. Consequences: the two creating calls need an
Idempotency-Key, so their forms render `IdempotencyKeyInput`; the checklist counts known and
not-applicable answers and returns an unsure one as the next question again, so a questions step
that lets a person move past "Not sure" keeps its own list of what was skipped; the business id is
the entity node's id, and a registration is addressed by `nodeId` inside an answer. Because a feature may not import
another, the onboarding steps that create and question a business are views of the business
feature, next to the business pages, and the attribute controls live there too.

## D-026: A consent's notice version names its document

2026-09-29. `docs/legal/consent-record.md` asks every grant to carry the version of the notice
the person saw, and the drafts in docs/legal all start at the same `Version:` value, so the bare
value could not tell the terms from the privacy notice. The web app records
`<document>@<Version line>` (`terms-of-service@0.1-draft`), read from the files at request time,
with each purpose mapped to the document it refers to (`PURPOSE_DOCUMENT` in
`features/consents/model/purposes.ts`). Consequences: a new Version line on a document makes the
step ask again for the purposes that refer to it and nothing else; the value fits the service's
40-character limit, which the model checks; the seed's demo consents, written with the bare
version, do not count as current for a user of the web app, which is harmless because the
seed's owner is not a user the fake sign-in can mint.

## D-027: The e2e suite reads the services from the consent step on

2026-09-29. D-011 and D-022 kept `make web-e2e` a build plus Playwright because no page called a
service. The consent step at `/onboarding` reads and writes identity and notification, so its
spec needs the stack and the seed, like the seeded-tenant sign-in: it is skipped locally without
`var/seed/last.json` and fails on CI without it. `make web-e2e` now points the app at the stack
(`CW_WEB_<SERVICE>_URL` from `SERVICE_PORT_BASE` and the Makefile's service order, unless the
environment already names one), so a second working copy on 9201-9210 runs the suite without an
`apps/web/.env.local`. Consequences: the local sequence is `make web-stack`, `make
web-stack-wait`, `make web-seed`, `make web-e2e`, `make web-stack-down`; a page whose read fails
still renders its h1 and the service's problem (`ServiceError` with a heading), so the page sweep
reports an unreachable service as a failed read rather than a missing heading.

## D-028: The business step shows what the lookup returned before it moves on

2026-09-29. The first design registered the GSTIN, ran the pre-fill as a second call and
redirected straight to the questions, with the pre-fill panel on the way. `POST /v1/businesses`
now does both in one call and answers with the pre-fill and the first question, so the step keeps
the answer on screen instead: the business (new, or already on file for that PAN), the values the
GSTIN lookup returned worded by the ontology, the attributes it stored, or the plain note and the
review task when no lookup provider answered, then a link to the questions. The form carries the
Idempotency-Key minted for its render; "Add another business" is a document load, so the next
form has a new key rather than replaying the first answer. The step shows the form only once the
required consents are on file, because the profile service does not check them, and
`createBusiness` checks them again before any profile call, because a server action can be
posted without the page (`server/required-consents.ts`, one check for both). Consequences: a
reload after adding forgets the panel (the business stays; the list and the business pages show
it); the page sweep leaves live pages with route parameters (a legal document, a business) to
their own specs, which visit them with real ids and run axe there.

## D-029: The questions step keeps its own skip list; a missing business is a streamed not-found

2026-09-29. The business API's checklist names an unsure question as the next one again, so a
step that only followed `next` would ask the same question after every "Not sure". The step keeps
the items answered "Not sure" in an httpOnly cookie per business (node id and attribute key, a
day, path `/onboarding`, written only by server actions) and walks the checklist past them; the
summary lists them and can ask them again. Considered and rejected: the question in the URL
(the plan keeps answers and questions out of URLs) and a server-side store (none exists for web
state). The business pages stream behind their `loading.tsx`, so, as Next documents, a business
that is missing or not the tenant's is the streamed not-found page (status 200, the not-found UI
and a `noindex` robots tag) rather than a 404 status; the id is checked before any service call.
A table that can be wider than its column names its scroll container (`scrollLabel` on the kit's
`Table`) so the region is focusable and axe's scrollable-region rule holds.

## D-030: The businesses search is posted, and a business's pages share one header

2026-09-29. The CA client list searches by name, PAN or GSTIN, and a PAN or a GSTIN in a query
string would land in the browser history and in access logs, which the web app rules out for
identifiers. The search box and the pager post to a server action and the client component redraws
the table from its answer; the cursor travels in the same body. The cost is that a searched page
is not bookmarkable and the back button leaves the list; the unfiltered first page is rendered on
the server. A business's pages share a header built from the registry (`businessHeaderLinks`):
breadcrumbs with the business's name, and a row of tabs from the business group's entries under
`/b/[businessId]`, including the screens not built yet, which lead to their notices. Nodes are
named by PAN, GSTIN or label with their name, because the business API names a registration after
its business unless told otherwise. Found while building the snapshot page: the snapshot route's
`lineage` holds the ancestors only, so the origin model now treats `business_id` as the node
itself (the earlier fixture had listed the node in its own lineage). The e2e sign-in waits for the
form to hydrate before typing the tenant id, a controlled input that hydration would otherwise
reset, which had sent an occasional spec into a new, empty tenant.

## D-031: Settings change consents as new records and remember recipients per device

2026-09-29. The consents page lets a user withdraw and also give the optional purposes (WhatsApp
reminders, email reminders, analytics). Giving is there because the notification page (next)
opts a number in only while the channel's consent is given, and a user who withdrew would
otherwise have no way back on the web; the required purposes stay with the consent step and
the data rights request. Every change is a new record, with `web_onboarding` as the source
because the identity service has no settings source; the evidence says it was confirmed on the
settings page and quotes the sentence shown. Withdrawing WhatsApp reminders opts the number out
before the record is written, so a failure leaves reminders stopped rather than a withdrawal on
file with reminders still going. The service does not return the user's own number or address
yet, so the number used on the consent step or the settings pages is remembered on the device
in an encrypted, httpOnly cookie bound to the user id (path `/settings`, 30 days, expired at
sign-out); considered and rejected: asking for the number on every visit (a withdrawal would
often leave the number opted in) and a hidden form field (it would put the number in the page
for anyone to change). The settings index is registry-driven and sits in the account group so
the header links to it; the settings pages share a header with breadcrumbs and tabs from the
settings group, planned entries left to the index.

## D-032: The notifications page opts in only with the channel's consent on file

2026-09-29. The notification service records any opt-in it is sent; it does not look at the
identity service's consents. The WhatsApp consent notice says the consent is recorded first and
the preference set after it, so `savePreference` reads the user's consents and refuses to switch
reminders on while the channel's purpose is not granted, naming the purpose and pointing to the
consents page; opting out, the language and the quiet hours are never held back. The page
writes to the recipient this device remembers, not to one named in the form, so a form cannot be
aimed at another number; choosing another recipient is its own step. The number and address
forms check their values on the server only (the browser's own email check is off), so the
messages are the same in every browser. Consequence: a number opted in by writing START on
WhatsApp shows as opted in here even without the web consent, and the page says the consent is
not on file.

## D-033: Billing shows the provider's answer, including "not connected"

2026-09-29. The billing page shows the plans exactly as the identity service states them and
starts a subscription with its provider; the web app decides no price and never takes payment
details. The stack the e2e suite runs on has no billing provider (`CW_BILLING_PROVIDER=none`), so
subscribing answers 503 `billing-disabled`; the form shows that as its own honest state ("billing
is not connected yet", nothing started, nothing charged, the request id) rather than as a
failure, and the spec asserts it. `make web-stack BILLING=memory` starts identity with the memory
provider for a manual demo, and `make web-e2e BILLING=memory` tells the spec to expect a started
subscription instead; the unit tests cover both answers. A form that refuses a submit puts the
submitted values back (React resets a form after its action), on this page and on the
notifications page.

## D-034: Product events are log lines behind the flag and a consent read on every event

2026-09-29. The onboarding funnel and the settings changes need product events, third-party
analytics are ruled out, and `docs/legal` makes analytics an optional purpose the person can
withdraw. `server/analytics.ts` writes each event as one JSON line on stdout and adds it to the
active OpenTelemetry span (`@opentelemetry/api`, pinned at 1.9.1, is the API Next's own tracing
resolves first; with no tracer registered the span event is a no-op). An event goes out only
while `web.analytics_enabled` is on, read through the new `server/flags.ts` over
`@compliancewatch/flags/server`, and the person's latest analytics record grants it at the
privacy notice's current version, read from identity on every event. Considered and rejected:
the session's `analyticsConsent` claim, which would keep events flowing after a withdrawal until
the session is refreshed; and running `track` in Next's `after()`, which needs a request scope the
unit tests do not have, for a cost (one consent read) paid only while the flag is on. The web
override variables count in local and test only; elsewhere the reader strips them, so Unleash is
the only way to switch a web flag on in staging or production. Consequences: with the flag off
nothing is read or written; with it on, each event adds one identity read to the action or page
that emits it; the events are a closed union, so a new one is a code change reviewed for
personal data; turning the flag on waits for counsel's view on the analytics purpose.

## D-035: Production onboarding is closed while the terms or the privacy notice is a draft

2026-09-29. Every document in `docs/legal` is still a draft waiting for a lawyer, and a consent
records the version a person agreed to, so a person agreeing in production would agree to a
draft. `onboardingGate()` in `server/legal.ts` closes onboarding when `CW_WEB_ENV` is `prod` and
any required document (`REQUIRED_LEGAL_DOCS`: the terms and the privacy notice, the documents the
required purposes refer to; a test holds the list to the purpose mapping) has a Version line
ending in `-draft`. Closed means: the consent step and the business step show the step's heading,
the draft banner and each draft with its version and link, and no form; `recordConsents` and
`createBusiness` refuse before any call; the consents settings page refuses to give a consent,
while a withdrawal is always recorded. Local, test and staging stay open under the draft banner,
so the flow can be built, tested and reviewed before the wording is approved; the WhatsApp
consent notice, for an optional purpose, does not close anything. The questions, the summary and
the business pages stay open, because they change a business that already exists. The legal
pages show the draft banner only while a document's version ends in `-draft` (a plain version
line afterwards, where the first build showed the banner whatever the version), and a print
stylesheet in `globals.css` prints the page without the shell, in black on white whatever the
screen's scheme, keeps the banner on a printed draft, and adds a line naming the document and its
version. Consequences: production onboarding opens with the release that carries the reviewed
Version lines, with no configuration change; the e2e suite runs in `test` and never sees the
closed state, which the unit tests cover.
