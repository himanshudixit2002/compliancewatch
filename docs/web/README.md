# Web app docs

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14, 15 and 19.

- **Owns:** The documentation of `apps/web` (the Next.js app) and `packages/ui` (the design
  system): how the code is arranged, why it is arranged that way, how a screen is added and
  how the app is tested
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
2. [design-system.md](design-system.md): tokens, light and dark schemes, the component
   inventory with the accessibility contract of each component, the catalogue at `/design`.
3. [adding-a-screen.md](adding-a-screen.md): the procedure for a new screen, including a
   screen whose backend does not exist yet and the flip from waiting to live.
4. [testing.md](testing.md): unit tests, the axe matcher, Playwright, coverage floors, the CI
   jobs and the make targets.
5. [i18n.md](i18n.md): the message table, `t()`, and the date, financial-year and money
   helpers.
6. [feature-flags.md](feature-flags.md): how a flag is declared.
7. [decisions.md](decisions.md): the log of decisions local to the web app, `D-001` onward.
8. [screens.md](screens.md): generated; every registry entry with its route, roles, status and
   what it waits for, plus the role-by-screen matrix.
9. [glossary.md](glossary.md): the words the code and these docs use.

The package READMEs ([apps/web/README.md](../../apps/web/README.md),
[packages/ui/README.md](../../packages/ui/README.md)) carry the layout trees and the run
commands; the docs here carry the reasoning and the procedures.

## How the docs stay current

| Change                                                             | What to update                                                                                                 |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| A registry entry: a new screen, a status flip, an awaited route    | `pnpm --filter web screens:gen` rewrites `screens.md`; `make check` and the unit tests fail while it is stale  |
| A layer rule or a new directory under `apps/web/src`               | `architecture.md` and the layout tree in `apps/web/README.md`                                                  |
| A token, a component, or a component's keyboard or ARIA behaviour | `design-system.md` and `packages/ui/README.md`                                                                 |
| The steps for adding or flipping a screen                          | `adding-a-screen.md`                                                                                           |
| A test convention, a coverage exclusion, a make target, a CI step  | `testing.md`                                                                                                   |
| A message key convention or a shared helper                        | `i18n.md`                                                                                                      |
| A flag declaration                                                 | `feature-flags.md`                                                                                             |
| A choice local to the web app                                      | A `D-0NN` entry in `decisions.md`; a choice that binds other parts of the platform is an ADR under `docs/adr/` |

## How to run

`pnpm --filter web screens:gen` regenerates `screens.md`; `pnpm --filter web screens:check`
(also `make web-screens-check`, part of `make check`) compares; `pnpm --filter web
screens:audit` lists the awaited routes that are still absent from the committed OpenAPI specs.
