// Generated from origin/main's packages/flags/registry.json and the Makefile's ## lines, for the
// mock only. The real helper reads the checkout's own files.

export const REGISTRY_FLAGS = [
  {
    name: "applicability.fanout",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_APPLICABILITY_FANOUT_ENABLED",
    description:
      "The applicability engine's consumer of rule.published (group applicability-engine.rules) starts a fan-out of the published version: a Temporal workflow on the applicability task queue that decides the version for every business of its level in the business directory, in batches of 1,000, behind the global hold and its pause, resume and cancel controls. Off, a publication records a disabled run and nothing else.",
    removal: "Once fan-outs have run in production for 30 days, under the flip-rate alert.",
    expires: "2027-03-31",
  },
  {
    name: "applicability.recompute",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_APPLICABILITY_RECOMPUTE_ENABLED",
    description:
      "The applicability engine's profile.updated consumer (group applicability-engine.profiles) evaluates the changed business and the registrations under it against every rule version in force, stores the decisions, publishes applicability.decided when a result applies or changes, and opens review items for free-text and low-confidence predicates. Off, the consumer only keeps the business directory.",
    removal:
      "Once recompute has run in production for 30 days and the rule.published fan-out reads the directory it keeps.",
    expires: "2027-03-31",
  },
  {
    name: "auth.mode",
    type: "string",
    owner: "platform",
    default: "header",
    env: "CW_AUTH_MODE",
    description:
      "How a Python service reads its caller (CW_AUTH_MODE): header takes the tenant from x-tenant-id as before tokens existed, dual verifies a bearer token from the identity service when a request carries one and otherwise behaves as header, token requires a bearer token on every route that reads the caller (probes, sign-in and reads that are the same for everyone stay open). Production refuses anything but token.",
    removal:
      "Delete header and dual once staging and production run token, after web sign-in (G68) and the bot and pipeline service credentials are live; production already refuses anything but token.",
    expires: "2027-03-31",
  },
  {
    name: "flags.provider",
    type: "string",
    owner: "platform",
    default: "env",
    env: "CW_FLAGS_PROVIDER",
    description:
      "Where py_common.flags and @compliancewatch/flags read flags: env from the environment, unleash from an Unleash server at CW_UNLEASH_URL with CW_UNLEASH_API_TOKEN.",
    removal: "Becomes plain configuration once a hosted Unleash runs in staging and production.",
    expires: "2027-03-31",
  },
  {
    name: "identity.auth_provider",
    type: "string",
    owner: "identity-partner",
    default: "fake",
    env: "CW_AUTH_PROVIDER",
    description:
      "The identity provider people sign in with (CW_AUTH_PROVIDER): fake signs provider tokens in the identity process for local runs and tests, supabase verifies Supabase Auth tokens and manages accounts through its admin API. Production refuses fake.",
    removal:
      "Kept as the provider selector (keycloak slots in for the Kubernetes profile). fake is refused when CW_ENV=prod, and the dev provider-token route only answers with fake in local or test.",
    expires: "2027-03-31",
  },
  {
    name: "identity.billing_provider",
    type: "string",
    owner: "identity-partner",
    default: "none",
    env: "CW_BILLING_PROVIDER",
    description:
      "The billing provider identity starts subscriptions with: none refuses them (503), memory keeps them in the process for tests and demos, razorpay calls Razorpay.",
    removal:
      "Becomes plain configuration once the Razorpay account, plans and keys work in production; none stays for local runs.",
    expires: "2027-03-31",
  },
  {
    name: "llm_gateway.provider",
    type: "string",
    owner: "ai-platform",
    default: "fake",
    env: "CW_LLM_PROVIDER",
    description:
      "The model provider the gateway calls: fake serves every route deterministically, vercel uses the Vercel AI Gateway and needs its key.",
    removal:
      "Becomes plain configuration once the AI Gateway account and key are live in staging and production; fake stays for tests and local runs.",
    expires: "2027-03-31",
  },
  {
    name: "mvp.worker_kafka",
    type: "bool",
    owner: "platform",
    default: false,
    env: "CW_WORKER_KAFKA_ENABLED",
    description:
      "Runs the outbox relays of every schema with an outbox_event table and every service's Kafka consumers in the combined worker process (cw-mvp worker).",
    removal: "When managed Kafka serves staging and production.",
    expires: "2027-03-31",
  },
  {
    name: "mvp.worker_temporal",
    type: "bool",
    owner: "platform",
    default: false,
    env: "CW_WORKER_TEMPORAL_ENABLED",
    description:
      "Runs every service's Temporal workers on one client in the combined worker process (cw-mvp worker).",
    removal: "When Temporal Cloud serves staging and production.",
    expires: "2027-03-31",
  },
  {
    name: "notification.bulk",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_NOTIFICATION_BULK_ENABLED",
    description:
      "Lets a CA firm send a change card to its affected clients in one request (POST /v1/notification/bulk): each client's own people get the card of the change once, deduplicated with the card the change itself made, through the usual queue, quiet hours and batching, and the request is audited as notification.bulk. Off, the route answers 503 and queues nothing.",
    removal:
      "Once CA firms have sent bulk notifications in production for 30 days with no duplicate card for one change to one business.",
    expires: "2027-03-31",
  },
  {
    name: "notification.email",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_EMAIL_ENABLED",
    description:
      "Wires the SMTP email channel in the notification service (CW_SMTP_HOST, CW_EMAIL_FROM and the SMTP credentials). Off, every email send fails with that reason and the fallback to email goes nowhere.",
    removal:
      "Removed when the in-region SMTP or SES sending domain is verified and email has run in production for 30 days. After that the channel is wired whenever CW_SMTP_HOST is set.",
    expires: "2027-03-31",
  },
  {
    name: "notification.whatsapp",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_WHATSAPP_ENABLED",
    description:
      "Wires the WhatsApp channel in the notification service. Off, every WhatsApp send fails with that reason.",
    removal:
      "Once the Meta business account, phone number and message templates are approved and WhatsApp sends in production.",
    expires: "2027-03-31",
  },
  {
    name: "obligation.reminder_sweep",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_OBLIGATION_SWEEP_ENABLED",
    description:
      "The obligation worker's reminder sweep and rolling window: every CW_OBLIGATION_SWEEP_INTERVAL_SECONDS the sweep publishes obligation.due_soon for open obligations due within 7, 3 and 1 days, once per obligation, due date and threshold, and once a day the window makes the obligations of the periods that entered it for every business whose latest decision of a recurring rule applies. Off, the worker only consumes its events.",
    removal: "Once reminders have gone out from the sweep in production for 30 days.",
    expires: "2027-03-31",
  },
  {
    name: "obligation.rule_events",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_OBLIGATION_RULE_EVENTS_ENABLED",
    description:
      "The obligation worker's consumer of the rule events (group obligation.rules): rule.published refreshes the rule_version_ref cache, rule.withdrawn closes the version's open obligations in every tenant, rule.superseded closes the periods the newer version takes over, and rule.deadline_changed moves the period's open obligations to the new date. Off, the group still consumes, so its offsets keep up, and changes nothing.",
    removal:
      "Once withdrawals, supersessions and deadline changes have reached obligations in production for 30 days.",
    expires: "2027-03-31",
  },
  {
    name: "pipeline.crawl",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_PIPELINE_CRAWL_ENABLED",
    description:
      "The pipeline crawls its sources: the worker's 60-second tick starts a crawl of every enabled, unpaused source whose cadence has passed, an admin may start one by hand (POST /v1/pipeline/sources/{key}/fetch), and the app reports each source's freshness gauges for the SourceStale alert. A crawl reads the live regulator sites, so it stays off on a laptop, in make product and in CI. Off, the tick starts nothing and the fetch route answers 503.",
    removal:
      "Once the 30-day F1 detection run (pipeline-crawl-report) passes in staging, every listed CBIC notification detected within 6 hours, and the crawl is on in production.",
    expires: "2027-03-31",
  },
  {
    name: "pipeline.extraction",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_PIPELINE_EXTRACTION_ENABLED",
    description:
      "The ingest extracts a rule candidate from each classified notification, circular or act amendment it registered: a child workflow asks the llm-gateway with the registered prompt extraction.rule_candidate@1 (once more when the answer is not a candidate, and later again while a budget is used up), stores the extraction and publishes rule.candidate.created in one transaction. It reads the document as the rulebook keeps it, so it needs pipeline.knowledge. Off, classified documents wait as classified and no model is called for them.",
    removal:
      "Once candidates from the extraction are reviewed into rules through the rulebook's candidate intake in staging and the extraction is on in production.",
    expires: "2027-03-31",
  },
  {
    name: "pipeline.knowledge",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_PIPELINE_KNOWLEDGE_ENABLED",
    description:
      "Hands parsed documents to the rulebook and embeds their clauses. Off, the worker makes no call to the rulebook or the gateway.",
    removal: "Once ADR-017 is accepted.",
    expires: "2027-03-31",
  },
  {
    name: "profile.gstin_category_prefill",
    type: "bool",
    owner: "core-product",
    default: false,
    env: null,
    description:
      "Writes business_category from the GSTIN lookup's nature of business when exactly one category maps.",
    removal:
      "When the nature-of-business mapping is reviewed against recorded provider responses and has been on for every tenant for 30 days.",
    expires: "2027-03-31",
  },
  {
    name: "profile.gstin_lookup",
    type: "string",
    owner: "core-product",
    default: "manual",
    env: "CW_PROFILE_GSTIN_LOOKUP",
    description:
      "The GSTIN lookup provider profile uses: manual has none, so every registration gets a verify_registration task; static serves the demo table; http asks the provider at CW_PROFILE_GSTIN_LOOKUP_URL, whose field mapping is reviewed against the provider's sandbox first.",
    removal:
      "Becomes plain provider configuration once the provider contract is signed; the manual fallback stays.",
    expires: "2027-03-31",
  },
  {
    name: "qa.kag",
    type: "bool",
    owner: "ai-platform",
    default: false,
    env: "CW_QA_KAG_ENABLED",
    description:
      "Runs the planner and solver layer (ADR-017) between the structured layer and hybrid search, for the listed tenants or, with no list, for every tenant.",
    removal: "When ADR-017 is Accepted.",
    expires: "2027-03-31",
  },
  {
    name: "rulebook.candidate_intake",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_RULEBOOK_CANDIDATE_INTAKE_ENABLED",
    description:
      "The rulebook worker's consumer of rule.candidate.created (group rulebook.rule-candidates): each rule candidate the pipeline's extraction publishes is stored once and queued for an analyst as a review task of kind candidate, at a priority and under its regulator. Analysts draft a version from it, never the intake. Off, no consumer group reads the topic, so the candidates wait there (it keeps a month) and the group reads them from the start once it is on.",
    removal:
      "Once candidates from the extraction are reviewed into rules through the review queue in staging and production for 30 days.",
    expires: "2027-03-31",
  },
  {
    name: "rulebook.publish",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_RULEBOOK_PUBLISH_ENABLED",
    description:
      "Publishing and withdrawing rule versions and the daily transition sweep. Off, those routes answer 503; citing and review still work.",
    removal:
      "Once the workbench publishes in production and the obligation consumer of the rule events is live.",
    expires: "2027-03-31",
  },
  {
    name: "web.admin_rulebook_writes",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES",
    description:
      "Entity and relation decisions from /admin through the web app's server-side rulebook write token. Off, the admin forms say which flag holds them back.",
    removal: "When the rulebook write routes take a bearer token and no shared token remains.",
    expires: "2027-03-31",
  },
  {
    name: "web.analytics_enabled",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "CW_WEB_FLAG_ANALYTICS_ENABLED",
    description:
      "Product events (JSON lines and span events) for web sessions that granted the analytics consent.",
    removal: "When counsel has confirmed the analytics consent purpose and events run everywhere.",
    expires: "2027-03-31",
  },
  {
    name: "web.otel_enabled",
    type: "bool",
    owner: "platform",
    default: false,
    env: "CW_WEB_FLAG_OTEL_ENABLED",
    description:
      "Registers OpenTelemetry in the web app's instrumentation.ts and exports spans over OTLP HTTP.",
    removal: "When OTLP export runs in every environment.",
    expires: "2027-03-31",
  },
  {
    name: "web.publish_actions",
    type: "bool",
    owner: "regulatory-intelligence",
    default: false,
    env: "CW_WEB_FLAG_PUBLISH_ACTIONS",
    description:
      "Citations and the publish workflow (submit, return, approve, publish, withdraw) on the web app's rule version page, sent with the review token. Off, the page says which flag holds them back.",
    removal: "When the publish workflow has run in staging for a release cycle.",
    expires: "2027-03-31",
  },
  {
    name: "web.qa_enabled",
    type: "bool",
    owner: "ai-platform",
    default: false,
    env: "CW_WEB_FLAG_QA_ENABLED",
    description: "The web app's ask screen on the qa ask route.",
    removal: "When the qa ask route is on for every tenant.",
    expires: "2027-03-31",
  },
  {
    name: "web.tenant_header_off",
    type: "bool",
    owner: "identity-partner",
    default: false,
    env: "CW_WEB_FLAG_TENANT_HEADER_OFF",
    description:
      "Stops the web app sending x-tenant-id once the services take the tenant from the bearer token.",
    removal: "When every service runs token mode and the tenant header is gone.",
    expires: "2027-03-31",
  },
  {
    name: "whatsapp_bot.consent_recording",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "WHATSAPP_CONSENT_RECORDING_ENABLED",
    description:
      "Records keyword opt-ins and opt-outs as channel consents in identity. Off, the bot logs what it would record.",
    removal: "Once the lawyer confirms keyword opt-in is valid consent.",
    expires: "2027-03-31",
  },
  {
    name: "whatsapp_bot.send",
    type: "bool",
    owner: "core-product",
    default: false,
    env: "WHATSAPP_SEND_ENABLED",
    description:
      "Lets the bot's replies leave the process through the WhatsApp Cloud API, with the phone number id and access token set.",
    removal: "Once the Meta business account is approved and the bot replies in production.",
    expires: "2027-03-31",
  },
];

export const MAKE_HELP = [
  ["help", " Show this help"],
  ["doctor", " Print which required tools are present"],
  ["dev", " Start Postgres, Redis, Redpanda, Temporal (+UI); waits for health, prints endpoints"],
  [
    "dev-observability",
    " Same as dev plus Langfuse, OTel collector, Prometheus, Tempo, Grafana (compose profile: observability)",
  ],
  ["dev-llm", " Build and start the fake LLM gateway container (compose profile: llm)"],
  ["dev-down", " Stop the stack, keep volumes"],
  [
    "dev-reset",
    " Stop the stack and delete volumes (infra/dev/postgres/init.sql runs again on next make dev)",
  ],
  ["dev-logs", " Tail logs; one service with SERVICE=postgres"],
  ["dev-ps", " Container status and health"],
  ["dev-psql", " psql into the application database"],
  ["dev-backup", " pg_dump the dev database into var/backups/<timestamp>.dump"],
  [
    "dev-restore",
    " Restore the dev database from a dump: make dev-restore FILE=var/backups/x.dump",
  ],
  ["compose-config", " Validate docker-compose.yml (CLI only, no daemon needed)"],
  ["py-sync", " Sync the Python workspace into .venv"],
  ["lock-check", " Fail if uv.lock is out of date with the pyproject files"],
  ["py-lint", " ruff check and ruff format --check"],
  ["py-format", " ruff format and ruff check --fix"],
  [
    "py-typecheck",
    " mypy --strict per package (src, tests, migrations/env.py), the root conftest and the repo scripts",
  ],
  ["py-test", " pytest: unit and contract tests with the coverage gate (no Docker needed)"],
  ["py-test-integration", " testcontainers tests; skipped gracefully when Docker is absent"],
  ["importlint", " import-linter contracts: no cross-service imports, domain imports no I/O"],
  ["ts-install", " pnpm install --frozen-lockfile"],
  ["ts-lint", " eslint per package (turbo, cached) + prettier check"],
  ["ts-format", " prettier --write"],
  ["ts-typecheck", " tsc --noEmit (strict) per package via turbo"],
  ["ts-test", " vitest run --coverage per package (thresholds in each vitest.config)"],
  ["ts-build", " next build + tsc build"],
  ["ts-dev", " next dev (:3000) and whatsapp-bot (:8080) with reload"],
  ["install", " Install both toolchains"],
  ["lint", " Lint both sides (CI step 1)"],
  ["format", " Auto-format both sides"],
  ["typecheck", " mypy --strict and tsc --strict (CI step 1)"],
  ["test", " Unit and contract tests on both sides (CI step 2)"],
  ["check", " Everything CI runs before integration tests (the gates listed in CHECKS)"],
  ["runbooks-check", " Every Prometheus alert links an existing runbook (guide section 18)"],
  [
    "eval",
    ' Eval harness against evals/golden: make eval [EVAL_PROFILE=ci|nightly] [ARGS="--provider fake --suite qa"]',
  ],
  [
    "eval-check",
    " KAG golden set and world well formed: quotes, seed supports, scripted plans and answers",
  ],
  [
    "demo",
    " The demo tenant end to end in one process (consent, profile, rules, obligations, reminder): make demo [ARGS=--json]",
  ],
  [
    "label",
    ' Labelling tool: make label ARGS="check" | "index --source cbic_notifications --since 2024-01-01 --out evals/golden/extraction/cbic_notifications/index.yaml" | "prepare --index ..."',
  ],
  ["migrate", " alembic upgrade head for every service, or one: make migrate SERVICE=identity"],
  ["run", " Run one service with reload: make run SERVICE=identity [PORT=8001]"],
  [
    "seed",
    " Load the rulebook seed calendar as draft rule versions: make seed SERVICE=rulebook [ARGS=--check]",
  ],
  [
    "backfill",
    ' Backfill one regulator source into var/raw: make backfill SERVICE=pipeline ARGS="--source cbic_notifications --since 2026-01-01"',
  ],
  [
    "crawl-report",
    ' Crawl runs, failures, gaps and detection delays per source, and the F1 check: make crawl-report [ARGS="--days 30 --json"]',
  ],
  [
    "worker",
    " Run a service's worker process, python -m <pkg>.worker (consumers, relay, periodic jobs, Temporal): make worker SERVICE=pipeline",
  ],
  ["relay", " Run the outbox relay for one service's schema: make relay SERVICE=obligation"],
  [
    "openapi",
    " Export a service's OpenAPI spec: make openapi SERVICE=llm-gateway -> packages/contracts/openapi/<svc>.v1.json",
  ],
  [
    "contracts",
    " Generate the event clients (pydantic + TypeScript) and the Python REST models (openapi/clients.json)",
  ],
  [
    "contracts-check",
    " Event schemas pass the 2020-12 metaschema, every topic in code has one, the generated clients match them, and public.v1.json is current",
  ],
  ["hooks", " Install the pre-commit and commit-msg hooks"],
  ["ci-lint", " Validate GitHub Actions workflows and the pre-commit config without running them"],
  [
    "migrations-check",
    " Migration files: one head per service, names match revisions, downgrades, marked contract steps",
  ],
  [
    "migrations-catalog",
    " After make migrate: tenant tables have forced row-level security (rules in infra/scripts/migration_lint.toml)",
  ],
  [
    "alerts-check",
    " promtool: alert rules parse and their unit tests pass (infra/dev/prometheus/alerts.test.yml)",
  ],
  ["openapi-check", " Every service that serves API routes commits its spec and a contract test"],
  [
    "openapi-compat",
    " Committed specs break no client of a base ref: make openapi-compat [BASE=origin/main]",
  ],
  [
    "sast",
    " Semgrep: registry packs and the rules in .semgrep; an ERROR finding fails (writes semgrep.sarif)",
  ],
  [
    "deps-scan",
    " Trivy: fixable HIGH and CRITICAL vulnerabilities and misconfigurations (settings in .trivy.yaml)",
  ],
  ["ci-gate-check", ' Every ci.yml job is in the needs of the required "CI gate" job'],
  [
    "data-quality",
    " Rulebook data-quality checks on the local rulebook schema, or CW_DQ_DATABASE_URL: make data-quality [ARGS=--json]",
  ],
  ["flags", " Write py-common's copy of the flag registry, then run flags-check"],
  [
    "flags-check",
    " Flag registry: schema, owners, expiry, bool defaults off, py-common copy current, every switch in settings registered",
  ],
  [
    "dev-flags",
    " Start Unleash for CW_FLAGS_PROVIDER=unleash (compose profile: flags); creates its database when missing",
  ],
  [
    "openapi-public",
    " Merge the operations the services tag public into packages/contracts/openapi/public.v1.json (after make openapi SERVICE=x), then regenerate the Python REST models",
  ],
  [
    "web-dev",
    " next dev on WEB_PORT from .env; /admin lists the internal tools, /design the UI kit",
  ],
  [
    "web-stack",
    " UI-only stack, no worker: every service on SERVICE_PORT_BASE+1..10 with memory stores (pids and logs in var/web-stack): make web-stack [STORE=postgres] [BILLING=memory]",
  ],
  [
    "web-stack-wait",
    " Wait until every web-stack service answers /health (WEB_STACK_WAIT_SECONDS, default 60)",
  ],
  [
    "web-stack-down",
    " Stop the web-stack services and remove their pid files (logs stay in var/web-stack)",
  ],
  ["control-panel", " Open the click-to-run control panel window (tools/control-panel)"],
  [
    "control-panel-app",
    " Build ComplianceWatch.app on the Desktop: make control-panel-app [DEST=~/Applications]",
  ],
  [
    "web-stack-logs",
    " Tail a web-stack service's log: make web-stack-logs SERVICE=identity (every log without SERVICE)",
  ],
  [
    "web-seed",
    ' Seed the web-stack services with the demo tenant and a recorded notification: make web-seed [ARGS="--tenant <uuid> --json"]',
  ],
  [
    "web-e2e-install",
    " Download Chromium for Playwright, once per machine (the package has no install script)",
  ],
  [
    "web-e2e",
    " Build the web app and run Playwright with axe against next start on WEB_PORT and the web-stack services (after make web-stack-wait and make web-seed)",
  ],
  ["web-screens", " Regenerate docs/web/screens.md from the screen registry"],
  ["web-screens-check", " docs/web/screens.md matches the screen registry (part of make check)"],
  [
    "openapi-ts",
    " Generate TypeScript types from packages/contracts/openapi into clients/typescript/openapi",
  ],
  [
    "openapi-ts-check",
    " The generated OpenAPI types match the committed specs (part of make check)",
  ],
  [
    "product",
    " The local product: make dev, make migrate, the seed calendar, cw-mvp serve and worker (Kafka, Temporal on), next dev on WEB_PORT (3000): make product [WEB=0] [WEB_PORT=3400]",
  ],
  [
    "product-role",
    " Create or refresh PRODUCT_DB_USER, the product's role under row-level security, on the running Postgres (after make migrate)",
  ],
  [
    "product-wait",
    " Wait for the product: the internal listener ready, the worker healthy and the web app answering (PRODUCT_WAIT_SECONDS, default 120)",
  ],
  [
    "product-seed",
    ' Fill the running product: synthetic tenants, the demo publication, first decisions (cw-product seed): make product-seed [ARGS="--rule gstr9_annual --json"]',
  ],
  [
    "product-check",
    ' Prove the running product works, step by step (cw-product check; exit 0 means accepted): make product-check [ARGS="--step loop --json"] [ARGS="--destructive"] (CI only)',
  ],
  [
    "product-e2e",
    " Build the web app and run the Playwright product project against the running product (after make product and make product-seed): make product-e2e [PRODUCT_E2E_PORT=3400]",
  ],
  [
    "product-down",
    " Stop the product's processes: only the pids make product recorded in var/product, with their children (logs stay)",
  ],
  [
    "product-logs",
    " Show a product process's log: make product-logs PROC=app|worker|web [FOLLOW=0]",
  ],
  [
    "mvp-image",
    " Build the one deployable's image (composition/mvp/Dockerfile) as MVP_IMAGE (compliancewatch-mvp:local)",
  ],
  [
    "product-image",
    " The local product from the image: make dev, the image, cw_app, cw-mvp release, serve and worker in containers, the seed calendar: make product-image [MVP_BUILD=0]",
  ],
  [
    "product-image-down",
    " Remove the image product's containers (mvp-release, mvp-app, mvp-worker); the dev stack keeps running",
  ],
  [
    "product-image-logs",
    " Show a container's log of the image product: make product-image-logs PROC=app|worker|release [FOLLOW=0]",
  ],
];
