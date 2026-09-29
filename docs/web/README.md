# Web app docs

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14, 15 and 19.

- **Owns:** The documentation of `apps/web` (the Next.js app) and `packages/ui` (the design
  system): how the code is arranged, why it is arranged that way, how the app talks to the
  services and who may open what, how a screen is added and how the app is tested
- **Owning team:** Core Product (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** n/a

These files describe the code on `main`. A doc changes in the same pull request as the code it
describes, and nothing here describes work that has not landed. `screens.md` is generated from
the screen registry; every other file is written by hand.

## Layout

Flat; markdown files. Reading order for someone new to the app:

1. [architecture.md](architecture.md): layers and import rules, the screen registry, how a
   request flows through the app, what runs in the browser and what on the server, the
   configuration files.
2. [data-layer.md](data-layer.md): how the server calls the services: the generated types, the
   clients and their headers, `Result` and the problem mapping, server actions and
   `ActionState`, caching and revalidation, idempotency and natural keys, the shared secrets,
   and the local services with their seed.
3. [auth-and-roles.md](auth-and-roles.md): roles and tenant kinds, the session cookie, the
   proxy and the gates, the sign-in provider port and the fake adapter, what is not enforced
   yet and what the identity work changes.
4. [design-system.md](design-system.md): tokens, light and dark schemes, the component
   inventory with the accessibility contract of each component, the catalogue at `/design`.
5. [adding-a-screen.md](adding-a-screen.md): the procedure for a new screen, including a
   screen whose backend does not exist yet and the moves from waiting to ready to live.
6. [testing.md](testing.md): unit tests, the axe matcher, Playwright, coverage floors, the CI
   jobs and the make targets.
7. [i18n.md](i18n.md): the message table, `t()`, and the date, financial-year and money
   helpers.
8. [feature-flags.md](feature-flags.md): how a flag is declared.
9. [decisions.md](decisions.md): the log of decisions local to the web app, `D-001` onward.
   The platform-level one, that the browser never calls a service and the session is an
   encrypted cookie, is [ADR-019](../adr/ADR-019-web-server-layer-and-stateless-session.md).
10. [screens.md](screens.md): generated; every registry entry with its route, roles, status and
    what it waits for, plus the role-by-screen matrix.
11. [glossary.md](glossary.md): the words the code and these docs use.

The package READMEs ([apps/web/README.md](../../apps/web/README.md),
[packages/ui/README.md](../../packages/ui/README.md)) carry the layout trees and the run
commands; the docs here carry the reasoning and the procedures.

## How the docs stay current

| Change                                                                   | What to update                                                                                                 |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| A registry entry: a new screen, a status flip, an awaited route          | `pnpm --filter web screens:gen` rewrites `screens.md`; `make check` and the unit tests fail while it is stale  |
| A layer rule or a new directory under `apps/web/src`                     | `architecture.md` and the layout tree in `apps/web/README.md`                                                  |
| A client, header, cache tag, idempotent operation, natural key or secret | `data-layer.md`                                                                                                |
| A role, a gate, a session claim, a sign-in adapter                       | `auth-and-roles.md`                                                                                            |
| A token, a component, or a component's keyboard or ARIA behaviour        | `design-system.md` and `packages/ui/README.md`                                                                 |
| The steps for adding or flipping a screen                                | `adding-a-screen.md`                                                                                           |
| A test convention, a coverage exclusion, a make target, a CI step        | `testing.md`                                                                                                   |
| A message key convention or a shared helper                              | `i18n.md`                                                                                                      |
| A flag declaration                                                       | `feature-flags.md`                                                                                             |
| A choice local to the web app                                            | A `D-0NN` entry in `decisions.md`; a choice that binds other parts of the platform is an ADR under `docs/adr/` |

## How to run

`pnpm --filter web screens:gen` regenerates `screens.md`; `pnpm --filter web screens:check`
(also `make web-screens-check`, part of `make check`) compares; `pnpm --filter web
screens:audit` lists the awaited routes that are still absent from the committed OpenAPI specs.
