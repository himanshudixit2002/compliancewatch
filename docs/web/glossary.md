# Glossary

The words the web app's code and docs use, with the file that owns each one where there is
one. Domain terms follow the guide and the services; the last two groups are the app's own.

## Domain

- **Tenant**: the account that owns data: a business, a CA firm or the internal organisation.
  Every service call carries the tenant id, and a screen's `tenantKinds` says which kinds may
  open it (`shared/config/roles.ts`).
- **Business**: a legal entity (PAN) with its registrations (GSTIN) and locations, the hierarchy
  the profile service keeps (ADR-016). Business-scoped routes start with `/b/[businessId]`.
- **Registration**: one GSTIN of a business; the node most obligations attach to.
- **Node**: any level of the business hierarchy (entity, registration, location); attributes and
  snapshots are read per node and financial year.
- **Attribute**: one fact about a node from the ontology (the profile service's attribute set,
  served worded at `GET /v1/ontology`); answered during onboarding, inherited down the hierarchy.
- **Ontology**: the attributes a profile holds, with their type, level, source, question, help
  line and value labels, and the operators a rule may use per type; versioned (`0.2.0`).
- **Financial year**: 1 April to 31 March, labelled `2026-27` (`shared/lib/financial-year.ts`).
- **Obligation**: a dated thing a business must do, materialised per period from a published
  rule version (ADR-015).
- **Rule version**: one version of a rule in the rulebook, with a status and a lifecycle
  (draft, review, published, withdrawn); a change is a new version, never an edit in place.
- **Citation**: the clause of a regulator document a rule version rests on; shown by
  `CitationCard` with the quote as stored, never paraphrased.
- **Clause**: a numbered piece of a regulator document the rulebook stores and searches.
- **Review task**: a question an analyst answers: an unverified registration, an entity to
  resolve, a candidate to decide.
- **Candidate**: something a pipeline proposed and an analyst has not approved yet: an entity
  mention, a relation, a rule.
- **Fan-out**: the applicability engine's re-evaluation of every affected business after a
  rule version is published.
- **Problem**: an error body in the RFC 9457 `application/problem+json` shape that every
  service returns, with a stable `type` and the request's correlation id.
- **Correlation id**: the `x-request-id` a call carries; `ErrorState` shows it in `<code>` with
  a copy button so support can find the log line.

## Roles and access

- **Role**: one of `owner`, `staff`, `ca_admin`, `ca_staff`, `compliance_lead`, `analyst`,
  `reviewer`, `admin`. Tenant members are the first five; regulatory (internal) roles are the
  last three and open `/admin`.
- **Capability**: what a screen or action asks for (`obligations.read`, `admin.publish`);
  `permissions.ts` maps each to its roles and `can()` answers for a principal.
- **Principal**: the minimum a gate needs to know about a session: roles and tenant kind.
- **Public**: a screen that needs no session (`roles: "public"`).

## The app

- **Screen**: an entry in the registry (`shared/config/screens.ts`): a page, a route handler,
  or a component or capability embedded in a page.
- **Registry**: the `SCREENS` list; the single source for navigation, sitemap, tool list,
  not-available pages, the accessibility sweep and `screens.md`.
- **Planned, waiting, ready, live**: a screen's status, in the order a screen moves through
  them. Planned: nobody has scheduled the backend. Waiting: at least one route or file it needs
  is absent. Ready: everything it needs is on `main`, but the screen is not built. Live: built,
  and every route it calls exists.
- **Uses, awaits**: the routes a screen calls today, and the routes it still needs. Each
  awaited route has an owner: the services track, the KAG track, or nobody.
- **Catch-all**: `(app)/[...slug]` and `admin/[...slug]`, the routes that render every planned,
  waiting or ready screen from its registry entry.
- **Not available yet**: the page a planned, waiting or ready screen renders: title, guide
  reference, roles and the awaited routes, or the sentence that no backend exists yet; for a
  ready screen, the sentence that its backend is on main and the screen is not built.
- **Flip**: moving an entry along its statuses: waiting to ready once its routes have landed,
  ready to live once the screen is built ([adding-a-screen.md](adding-a-screen.md)).
- **Feature**: a directory under `src/features` for one screen family: `model/`, `ui/`,
  `index.ts`, and the port, gateway, queries and actions files where the feature reads or
  writes.
- **Entity**: a directory under `src/entities`: pure domain types and DTO-to-view mappers.
- **Shell**: the frame around a page: `TenantShell` (over the kit's `AppShell`) for public and
  tenant pages, `InternalShell` (over `AdminShell`) for `/admin`.
- **Token**: a named design value (`bg`, `fg-muted`, `danger`, `radius-md`) declared in
  `packages/ui/src/styles/tokens.css` and reached through a Tailwind class such as `bg-bg`.
- **Tone**: the status vocabulary `neutral`, `success`, `warning`, `danger`, `info` shared by
  Badge, StatusChip, Banner and Timeline.
- **Catalogue**: `/design`, every component in every state, local and test only.
- **Guide reference**: the section of the Project Foundation guide (or the ADR) a screen comes
  from, kept on every registry entry.
- **Draft banner**: the fixed "Draft - to be reviewed by a lawyer" line every legal page shows
  while the document's `Version:` ends in `-draft`.
- **Closed onboarding**: the consent and business steps in production while the terms or the
  privacy notice is a draft: no form, and their actions record nothing (`onboardingGate()` in
  `server/legal.ts`; [legal-pages.md](legal-pages.md)).
- **Notice version**: what a consent record says was agreed to, `<document>@<Version line>`,
  such as `privacy-notice@0.1-draft`.
- **Skip list**: the questions a person answered Not sure in onboarding, kept per business in an
  httpOnly cookie so the step moves past them ([onboarding-flow.md](onboarding-flow.md)).
- **Product event**: one JSON line and span event from `server/analytics.ts`, emitted only with
  `web.analytics_enabled` on and the person's analytics consent current.
- **Message key**: a key of `messages/en.json`, namespaced by feature, read through `t()`.
- **Date key**: a `YYYY-MM-DD` string in IST; the form dates take between the app and the
  services.

## Data and sessions

- **Server layer**: `src/server`, the only code that calls a service or reads a secret; every
  file starts with `import "server-only"` (ADR-019, [data-layer.md](data-layer.md)).
- **Result**: what a service call or a query returns: `{ ok: true, value }` or
  `{ ok: false, error }` with an `ApiError` (`server/result.ts`).
- **ApiError**: a failure's `kind` (from the status: `validation`, `conflict`, `network`, ...),
  the problem, the request id and field errors.
- **ActionState**: what a server action returns to its form: `idle`, `ok` or `error` with the
  problem, field errors and form errors (`shared/lib/action-state.ts`).
- **Cache tag**: the name a cached global read is stored under and a server action expires
  (`tags.*` in `server/cache.ts`).
- **Natural key**: the field a service uses to find an existing record on a repeated create
  (a GSTIN, a PAN, a document's sha256), which makes the write safe to repeat.
- **Session**: the encrypted `cw_session` cookie and the claims in it
  ([auth-and-roles.md](auth-and-roles.md)).
- **Gate**: a function in `server/dal.ts` a page, action or handler calls first:
  `requireScreen`, `requireRole`, `requireAdmin`, ...
- **Proxy**: `src/proxy.ts`, the check before a render that sends a visitor without a session
  cookie to sign-in.
- **Provider**: the sign-in adapter behind `AuthProvider`; `fake` in local and test today.
- **Web stack**: every service on memory stores, started by `make web-stack` for the app.
- **Seed**: `make web-seed`, the demo tenant and one recorded notification written through the
  services' HTTP APIs; `var/seed/last.json` names the tenant.
