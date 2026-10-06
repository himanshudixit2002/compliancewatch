# onboarding

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13, 14 and 17.

- **Owns:** Engineer onboarding: local dev stack (Docker Compose), golden paths, team contacts, and the repository settings the owner applies by hand
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** n/a

## Layout

Flat; markdown guides.

- [local-dev.md](local-dev.md): tools, the Docker Compose stack, ports, running a service, troubleshooting.
- [demo.md](demo.md): the demo tenant end to end in one process (`make demo`).
- [product.md](product.md): the local product (`make product`, `make product-seed`, `make product-check`): the one deployable with its worker on the dev stack, synthetic tenants, and the check of the event chain.
- [control-panel.md](control-panel.md): ComplianceWatch Control, the desktop app (`make control-panel-app`, or `make control-panel` in the browser): what each section does, recipes, what it never does, and how it is built.
- [repository-settings.md](repository-settings.md): the `gh` commands for branch protection (the required `CI gate` check), squash merges, Dependabot, secret scanning and private vulnerability reporting, and the secrets CI needs.

## How to run

Start with [local-dev.md](local-dev.md). Before a pull request, `make check` runs the gates CI
runs without Docker; [CONTRIBUTING.md](../../CONTRIBUTING.md) lists them with the Docker-based
ones (`make py-test-integration`, `make alerts-check`, `make sast`, `make deps-scan`).
