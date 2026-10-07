// What the mock helper answers: the action catalog in plain words (as panel_core's plans run
// them), the parts of the stack in a few made-up states, and the data each view reads. Used by
// mock-server.mjs for development and the Playwright tests; never served by the real app.

import { SNAPSHOT } from "./mock-catalog.mjs";
import { MAKE_HELP, REGISTRY_FLAGS } from "./mock-registry.mjs";

export const SERVICES = [
  "identity",
  "profile",
  "rulebook",
  "applicability-engine",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
  "eval",
  "pipeline",
];
const WORKERS = ["applicability-engine", "notification", "obligation", "pipeline", "rulebook"];
const RELAYS = [
  "applicability-engine",
  "identity",
  "notification",
  "obligation",
  "pipeline",
  "profile",
  "rulebook",
];
export const CHECK_STEPS = [
  "health",
  "honesty",
  "loop",
  "isolation",
  "recompute",
  "fanout",
  "reminders",
  "tracking",
  "changes",
  "public",
  "sources",
  "review",
  "extraction",
];

export const GROUPS = SNAPSHOT.groups.map(([id, title]) => ({ id, title }));

const choices = (names) => names.map((name) => ({ value: name, label: name }));

/** The live choices the helper fills from the checkout, made up here. */
const CHOICES = {
  services: choices(SERVICES),
  workers: choices(WORKERS),
  relays: choices(RELAYS),
  "check-steps": choices(CHECK_STEPS),
  "product-procs": [
    { value: "app", label: "App" },
    { value: "worker", label: "Worker" },
    { value: "web", label: "Web app" },
  ],
  "image-procs": choices(["app", "worker", "release"]),
  docs: [
    { value: "local-dev", label: "Local development" },
    { value: "product", label: "The local product" },
    { value: "demo", label: "The five-minute demo" },
    { value: "control-panel", label: "This app" },
    { value: "runbooks", label: "Runbooks" },
  ],
  containers: choices(["postgres", "redis", "redpanda", "temporal", "temporal-ui"]),
  backups: [
    {
      value: "var/backups/20261006T101500Z.dump",
      label: "20261006T101500Z.dump · 4.2 MB, 3 h ago",
    },
    {
      value: "var/backups/20261002T083000Z.dump",
      label: "20261002T083000Z.dump · 3.9 MB, 4 days ago",
    },
  ],
};

/** The steps each plan streams (panel_core's labels) and its commands, for the pretend runner. */
const STEPS = {
  "start-everything": [
    "start Docker",
    "start databases and queues",
    "migrate databases",
    "start services",
    "wait for services",
    "start web app",
    "open http://localhost:3000",
  ],
  "stop-everything": [
    "stop web app",
    "stop the UI-only stack",
    "stop the product's processes",
    "stop the panel's workers and relays",
    "stop the dev stack's containers (make dev-down)",
    "stop Docker (colima stop)",
  ],
  "docker-start": ["start Docker"],
  "docker-stop": ["stop Docker"],
  "force-stop-docker": ["force-stop Docker (colima stop --force)"],
  "databases-start": ["make dev"],
  "databases-stop": ["make dev-down"],
  "dev-ps": ["make dev-ps"],
  "ui-start": ["make web-stack STORE=postgres", "wait for services"],
  "ui-stop": ["make web-stack-down"],
  "ui-restart": ["stop services", "make web-stack STORE=postgres", "wait for services"],
  "ui-wait": ["make web-stack-wait"],
  "web-start": ["start web app"],
  "web-stop": ["stop web app"],
  "product-start": ["start Docker", "make product WEB_PORT=3400"],
  "product-stop": ["make product-down"],
  "product-wait": ["make product-wait WEB_PORT=3400"],
  "product-role": ["make product-role"],
  "product-seed": ["check the product answers", "make product-seed"],
  "product-check": ["make product-check"],
  "product-e2e": ["make product-e2e PRODUCT_E2E_PORT=3401"],
  "mvp-image": ["make mvp-image"],
  "product-image": ["start Docker", "make product-image"],
  "product-image-down": ["make product-image-down"],
  "dev-observability": ["make dev-observability"],
  "dev-llm": ["make dev-llm"],
  "dev-flags": ["make dev-flags"],
  "worker-start": ["start the worker"],
  "worker-stop": ["stop the worker"],
  "relay-start": ["start the outbox relay"],
  "relay-stop": ["stop the outbox relay"],
  "load-demo-data": ["seed rulebook", "seed the demo tenant (UI-only stack)"],
  demo: ["make demo"],
  migrate: ["make migrate"],
  "seed-check": ["make seed SERVICE=rulebook ARGS=--check"],
  "migrations-catalog": ["make migrations-catalog"],
  "data-quality": ["make data-quality"],
  backup: ["make dev-backup"],
  restore: [
    "back up the database first",
    "check that pg_restore reads the dump",
    "make dev-restore",
  ],
  reset: [
    "back up the database first",
    "stop the UI-only stack",
    "stop the product's processes",
    "stop the panel's workers and relays",
    "make dev-reset",
    "make dev",
    "make migrate",
    "seed rulebook",
  ],
  "migrations-check": ["make migrations-check"],
  "product-logs": ["make product-logs"],
  "container-logs": ["docker compose logs --tail 200"],
  "gate:check": ["make check"],
  "gates-in-order": [
    "lint",
    "typecheck",
    "test",
    "importlint",
    "lock-check",
    "openapi-check",
    "flags-check",
    "eval-check",
    "eval (ci)",
  ],
  "gate:lint": ["lint"],
  "gate:typecheck": ["typecheck"],
  "gate:test": ["test"],
  "gate:py-test-integration": ["py-test-integration"],
  "gate:eval": ["eval (ci)"],
  "gate:eval-check": ["eval-check"],
  "gate:openapi-compat": ["openapi-compat"],
  "gate:contracts-check": ["contracts-check"],
  "gate:alerts-check": ["alerts-check"],
  "gate:flags-check": ["flags-check"],
  "gate:migrations-check": ["migrations-check"],
  "gate:sast": ["sast"],
  "gate:deps-scan": ["deps-scan"],
  "gate:web-screens-check": ["web-screens-check"],
  "gate:web-e2e": [
    "check that the test copy can start",
    "start a separate test copy of the services",
    "wait until the test copy answers",
    "add made-up demo data to the test copy",
    "build the web app and click through it in a robot browser",
    "stop the test copy",
  ],
  "gate:ci-lint": ["ci-lint"],
  "crawl-report": ["make crawl-report"],
  "flags-check": ["make flags-check"],
  doctor: ["make doctor"],
};

const COMMANDS = {
  "start-everything":
    "colima start --cpu 4 --memory 8 --disk 60 --dns 1.1.1.1 --dns 8.8.8.8   (only when Docker is not running)\nmake dev\nmake migrate\nmake web-stack STORE=postgres\nmake web-stack-wait\npnpm --filter web dev   (PORT=3000)\nopen http://localhost:3000",
  "stop-everything":
    "SIGTERM to the web app's processes (named first)\nmake web-stack-down\nmake product-down\nstop this app's workers and relays\nmake dev-down\ncolima stop",
  "docker-start": "colima start --cpu 4 --memory 8 --disk 60 --dns 1.1.1.1 --dns 8.8.8.8",
  "docker-stop": "colima stop",
  "force-stop-docker": "colima stop --force",
  "databases-start": "make dev",
  "databases-stop": "make dev-down",
  "dev-ps": "make dev-ps",
  "ui-start": "make web-stack STORE=postgres\nmake web-stack-wait",
  "ui-stop": "make web-stack-down",
  "ui-restart": "make web-stack-down\nmake web-stack STORE=postgres\nmake web-stack-wait",
  "ui-wait": "make web-stack-wait",
  "web-start": "pnpm --filter web dev   (PORT=3000)",
  "web-stop": "SIGTERM to the web app's process tree (never a process group)",
  "product-start":
    "colima start ...   (only when Docker is not running)\nmake product WEB_PORT=3400",
  "product-stop": "make product-down",
  "product-wait": "make product-wait WEB_PORT=3400",
  "product-role": "make product-role",
  "product-seed": "make product-seed   (no options, only while the product answers)",
  "product-check": 'make product-check   (or ARGS="--step <step>"; never --destructive)',
  "product-e2e": "make product-e2e PRODUCT_E2E_PORT=3401",
  "mvp-image": "make mvp-image",
  "product-image": "make product-image",
  "product-image-down": "make product-image-down",
  "dev-observability": "make dev-observability",
  "dev-llm": "make dev-llm",
  "dev-flags": "make dev-flags",
  "worker-start": "make worker SERVICE=<service>   (CW_PIPELINE_CRAWL_ENABLED=false)",
  "worker-stop": "SIGTERM to the worker's process group",
  "relay-start": "make relay SERVICE=<service>   (CW_PIPELINE_CRAWL_ENABLED=false)",
  "relay-stop": "SIGTERM to the outbox relay's process group",
  "load-demo-data": "make seed SERVICE=rulebook\nmake web-seed",
  demo: "make demo",
  migrate: "make migrate   (or SERVICE=<service>)",
  "seed-check": "make seed SERVICE=rulebook ARGS=--check",
  "migrations-catalog": "make migrations-catalog",
  "data-quality": "make data-quality",
  backup: "make dev-backup",
  restore: "pg_restore --list (reads the dump first)\nmake dev-restore FILE=<backup>",
  reset:
    "make dev-backup (when ticked)\nmake web-stack-down\nmake product-down\nmake dev-reset\nmake dev\nmake migrate\nmake seed SERVICE=rulebook",
  psql: "open -a Terminal var/control-panel/psql.command   (runs make dev-psql)",
  "migrations-check": "make migrations-check",
  "product-logs": "make product-logs PROC=<proc> FOLLOW=0",
  "container-logs": "docker compose logs --no-color --tail 200 <service>",
  "open-logs-folder": "open var",
  "open-backups-folder": "open var/backups",
  "gate:check": "make check",
  "gates-in-order": "make lint, make typecheck, make test, ... in CI's order",
  "gate:lint": "make lint",
  "gate:typecheck": "make typecheck",
  "gate:test": "make test",
  "gate:py-test-integration": "make py-test-integration",
  "gate:eval": "make eval EVAL_PROFILE=ci",
  "gate:eval-check": "make eval-check",
  "gate:openapi-compat": "make openapi-compat",
  "gate:contracts-check": "make contracts-check",
  "gate:alerts-check": "make alerts-check",
  "gate:flags-check": "make flags-check",
  "gate:migrations-check": "make migrations-check",
  "gate:sast": "make sast",
  "gate:deps-scan": "make deps-scan",
  "gate:web-screens-check": "make web-screens-check",
  "gate:web-e2e":
    "make web-stack-down STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400\nmake web-stack STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400\nmake web-stack-wait STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400 WEB_STACK_WAIT_SECONDS=180\nmake web-seed STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400\nmake web-e2e STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400 WEB_PORT=3410\nmake web-stack-down STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400",
  "gate:ci-lint": "make ci-lint",
  "crawl-report": "make crawl-report",
  "flags-check": "make flags-check",
  "open-env": "open -t .env",
  doctor: "make doctor",
};

/** What an action needs, as the helper words it when it is missing (and what fixes it). */
const NEED_OFF = {
  docker: ["Docker is not running.", "docker-start"],
  product: ["The product is not running.", "product-start"],
};

function curated(spec) {
  const params = (spec.params ?? []).map((p) => {
    const options = p.source ? (CHOICES[p.source] ?? []) : (p.choices ?? []);
    const first = p.required === false ? "" : (options[0]?.value ?? "");
    return { ...p, kind: p.kind ?? "choice", choices: options, default: p.default ?? first };
  });
  // what it needs, as panel_catalog.py says (docker, product): the helper disables it otherwise
  const need = spec.id === "docker-start" ? undefined : (spec.needs ?? [])[0];
  return {
    kind: "step",
    button: "Run",
    ...spec,
    params,
    steps: STEPS[spec.id] ?? [spec.title.toLowerCase()],
    command: COMMANDS[spec.id] ?? "",
    needs: need,
    reasonOff: need ? NEED_OFF[need][0] : "",
    fix_action: need ? NEED_OFF[need][1] : null,
  };
}

function gate(target, [title, summary, duration, what]) {
  const rewrites = target === "contracts-check";
  return {
    id: `gate:${target}`,
    title,
    summary,
    duration,
    group: "checks",
    safety: rewrites ? "changes-data" : "safe",
    button: "Check",
    confirm: rewrites ? "The generated clients are rewritten in the checkout." : "",
    what_happens: what ?? [
      `Runs make ${target === "eval" ? "eval EVAL_PROFILE=ci" : target} and shows whether it passed.`,
      rewrites
        ? "It rewrites the generated clients before it compares them; they show as changed files when they were out of date."
        : "It changes nothing.",
    ],
    steps: STEPS[`gate:${target}`] ?? [target],
    command: COMMANDS[`gate:${target}`] ?? `make ${target}`,
  };
}

/** The curated actions of panel_catalog.py, and a check per gate. */
export const CURATED = [
  ...SNAPSHOT.curated.map(curated),
  ...Object.entries(SNAPSHOT.gates).map(([target, words]) => gate(target, words)),
];

/**
 * Every ##-documented make target, in panel_catalog.py's words (MAKE_TEXTS): its plain title,
 * its safety, why it is refused, and the curated action that covers it.
 */
export function makeActions() {
  return MAKE_HELP.map(([target, help]) => {
    const text = SNAPSHOT.make[target] ?? {
      title: `make ${target}`,
      summary: help.trim(),
      what: [],
      duration: "",
      safety: "safe",
    };
    const refused = text.safety === "refused";
    const need = (text.needs ?? [])[0];
    return {
      id: `make:${target}`,
      group: text.group ?? "make",
      source: "make",
      title: text.title,
      summary: text.summary,
      what_happens: text.what,
      duration: text.duration,
      safety: refused ? "refused" : text.safety,
      kind: text.kind ?? "step",
      enabled: !refused,
      reason: text.refused ?? "",
      covered_by: text.covered_by || null,
      needs: need,
      reasonOff: need ? NEED_OFF[need][0] : "",
      fix_action: refused ? text.covered_by || null : need ? NEED_OFF[need][1] : null,
      takes: text.takes,
      migrates: text.migrates,
      rewrites: text.rewrites,
      keywords: `${target.replace(/-/g, " ")} ${target} make`,
      button: "Run",
      steps: [`make ${target}`],
      command: `make ${target}`,
    };
  });
}

// ---- the worlds the mock can be in ---------------------------------------------------------------

export function baseWorld() {
  return {
    demo: false,
    docker: false,
    infra: false,
    services: 0,
    web: false,
    product: { internal: false, public: false, worker: false, web: false },
    tools: false,
    background: {},
    branch: "main",
    dirty: 0,
    sessions: [],
  };
}

export function statusOf(world) {
  const infra = ["postgres", "redis", "redpanda", "temporal", "temporal-ui"].map((service) => ({
    service,
    label: {
      postgres: "Postgres 16 + pgvector",
      redis: "Redis 7",
      redpanda: "Kafka API (Redpanda)",
      temporal: "Temporal",
      "temporal-ui": "Temporal UI",
    }[service],
    profile: "core",
    state: world.infra ? "running" : world.docker ? "exited" : "",
    health: world.infra && service !== "temporal-ui" ? "healthy" : "",
    up: world.infra,
    ports: {
      postgres: [5432],
      redis: [6379],
      redpanda: [18081, 19092, 19644],
      temporal: [7233],
      "temporal-ui": [8233],
    }[service],
  }));
  if (world.tools) {
    infra.push(
      {
        service: "grafana",
        label: "Grafana",
        profile: "observability",
        state: "running",
        health: "",
        up: true,
        ports: [3030],
      },
      {
        service: "prometheus",
        label: "Prometheus",
        profile: "observability",
        state: "running",
        health: "",
        up: true,
        ports: [9090],
      },
    );
  }
  const running = [
    world.docker && "Docker",
    world.infra && "the databases",
    world.services && "the services",
    world.web && "the web app",
    world.product.internal && "the product",
  ].filter(Boolean);
  return {
    taken_at: Date.now() / 1000,
    demo: world.demo,
    summary: running.length ? `Running: ${running.join(", ")}.` : "Everything is stopped.",
    docker: { up: world.docker, detail: world.docker ? "Colima" : "" },
    infra: world.docker ? infra : [],
    services: SERVICES.map((name, index) => ({
      name,
      port: 8001 + index,
      up: index < world.services,
      url: `http://localhost:${8001 + index}`,
    })),
    web: { up: world.web, port: 3000, url: "http://localhost:3000" },
    product: {
      internal: { up: world.product.internal, port: 8080, url: "http://127.0.0.1:8080" },
      public: { up: world.product.public, port: 8000, url: "http://127.0.0.1:8000" },
      worker: { up: world.product.worker, port: 8081, url: "http://127.0.0.1:8081" },
      web: { up: world.product.web, port: 3400, url: "http://127.0.0.1:3400" },
    },
    background: [
      ...WORKERS.map((service) => ({
        key: `worker-${service}`,
        label: `${service} worker`,
        kind: "worker",
        service,
        pid: world.background[`worker-${service}`] ?? null,
      })),
      ...RELAYS.map((service) => ({
        key: `relay-${service}`,
        label: `${service} outbox relay`,
        kind: "relay",
        service,
        pid: world.background[`relay-${service}`] ?? null,
      })),
    ],
    checkout: {
      branch: world.branch,
      sha: world.branch === "main" ? "08b209f" : "b3e7e1b",
      subject:
        world.branch === "main"
          ? "feat: rule candidate intake and drafting for review (#76)"
          : "feat: list and replay dead letters with make replay",
      when: "2 hours ago",
      dirty: world.dirty,
      ahead: world.branch === "main" ? 0 : 5,
      behind: world.branch === "main" ? 0 : 2,
      is_main: world.branch === "main",
      error: "",
    },
    sessions: world.sessions,
    loading: false,
    level: world.web && world.services === 10 ? "running" : world.docker ? "partial" : "stopped",
    warnings:
      world.branch === "main"
        ? []
        : [
            {
              code: "not-main",
              message: `This checkout is on ${world.branch}, not main: anything you start runs that branch's code.`,
            },
          ],
  };
}

/** Claude's build agent running make check here, as the demo helper shows it. */
export const AGENT_SESSION = {
  pid: 61000,
  label: "make check",
  elapsed: 192,
  kind: "agent",
  uses: ["docker"],
  text: "make check (pid 61000, 3m 12s) with 3 more",
};

// ---- what the other views read ------------------------------------------------------------------

export function featuresOf(world) {
  const up = world.product.internal;
  const live = (numbers) => (up ? numbers : []);
  const state = up ? "live" : "not-running";
  return {
    features: [
      {
        id: "review-queue",
        title: "Review queue",
        summary: "Seed drafts and rule candidates waiting for an analyst.",
        state,
        numbers: live([
          { label: "Waiting", value: 13 },
          { label: "Claimed", value: 1 },
          { label: "Decided", value: 0 },
        ]),
        links: [
          { label: "Review queue", url: "", live: false },
          { label: "Review stats", url: "", live: false },
        ],
      },
      {
        id: "pipeline-tasks",
        title: "Pipeline tasks",
        summary: "Documents waiting for a person: triage and manual parsing.",
        state,
        numbers: live([
          { label: "Triage", value: 0 },
          { label: "Manual parse", value: 0 },
        ]),
        links: [{ label: "Pipeline tasks", url: "", live: false }],
      },
      {
        id: "dead-outbox",
        title: "Dead outbox events",
        summary: "Events a service could not publish, kept for a person to replay.",
        state: "not-built",
        numbers: [],
        links: [],
        note: "The product has no route for this yet.",
      },
      {
        id: "runs",
        title: "Crawl runs and retries",
        summary: "Each source's crawl runs and what is waiting to be tried again.",
        state: "not-built",
        numbers: [],
        links: [],
        note: "The product has no route for this yet.",
      },
      {
        id: "fan-out",
        title: "Fan-outs",
        summary: "Published rules decided for every business, with the hold.",
        state,
        numbers: live([
          { label: "Hold", value: "Off" },
          { label: "Completed", value: 2 },
          { label: "Paused", value: 0 },
        ]),
        links: [{ label: "Fan-outs", url: "http://127.0.0.1:3400/admin/fan-outs", live: up }],
      },
      {
        id: "obligations",
        title: "Obligations",
        summary: "The dated duties of the demo businesses.",
        state,
        numbers: live([
          { label: "Open", value: 14 },
          { label: "Due in 7 days", value: 3, tone: "warning" },
          { label: "Closed", value: 6 },
        ]),
        links: [],
      },
      {
        id: "changes",
        title: "Changes",
        summary: "Rule changes announced in the public changes feed.",
        state,
        numbers: live([{ label: "Changes", value: 3 }]),
        links: [{ label: "Impact explorer", url: "http://127.0.0.1:3400/admin/impact", live: up }],
      },
      {
        id: "notifications",
        title: "Messages through the sink",
        summary: "What the product would have sent, written to var/product/sink.jsonl.",
        state,
        numbers: live([
          { label: "Sent", value: 8 },
          { label: "Refused", value: 4, hint: "WhatsApp, outside 24 h" },
          { label: "Held", value: 1, hint: "For the daily digest" },
        ]),
        links: [
          { label: "Notifications", url: "http://127.0.0.1:3400/admin/notifications", live: up },
        ],
      },
      {
        id: "flags",
        title: "Flags",
        summary: "The switches in the flag registry.",
        state: "live",
        numbers: [
          { label: "Flags", value: 30 },
          { label: "Set on this Mac", value: 3 },
        ],
        links: [{ label: "Feature flags", url: "http://127.0.0.1:3400/admin/flags", live: up }],
      },
      {
        id: "product-check",
        title: "The last product check",
        summary: "How the product check went the last time it ran.",
        state: "live",
        numbers: [
          { label: "Passed", value: 13 },
          { label: "Failed", value: 0 },
          { label: "Skipped", value: 1 },
        ],
        links: [],
        note: "Ran 25 minutes ago.",
      },
      {
        id: "eval-report",
        title: "The last eval report",
        summary: "The AI parts measured against the golden sets.",
        state: "live",
        numbers: [
          { label: "Suites", value: 4 },
          { label: "Gates passed", value: "12 of 12" },
        ],
        links: [],
        note: "evals/reports/latest.md, written 2 days ago.",
      },
    ],
  };
}

export function flagsOf() {
  const values = {
    CW_LLM_PROVIDER: ["fake", ".env"],
    CW_PROFILE_GSTIN_LOOKUP: ["static", ".env"],
    CW_WEB_FLAG_QA_ENABLED: ["true", "apps/web/.env.local"],
  };
  return {
    flags: REGISTRY_FLAGS.map((f) => {
      const env = f.env ?? `CW_FLAG_${f.name.toUpperCase().replace(/\./g, "_")}`;
      const set = values[env];
      return {
        ...f,
        default: typeof f.default === "boolean" ? String(f.default) : String(f.default ?? ""),
        env,
        value: set ? set[0] : null,
        source: set ? set[1] : "",
      };
    }),
    error: "",
  };
}

export function processesOf(world) {
  const port = (port, what, group, pid, command, origin) => ({
    port,
    what,
    group,
    pid,
    command,
    origin,
  });
  const ports = [
    port(
      3000,
      "web app (next dev)",
      "UI-only stack",
      world.web ? 76180 : null,
      "next-server (v16.3.8)",
      "panel web app",
    ),
    port(
      3400,
      "product web app",
      "product",
      world.product.web ? 62200 : null,
      "next-server (v16)",
      "make product",
    ),
    port(5432, "Postgres", "infra", world.infra ? 1180 : null, "ssh (Colima port forwarding)", ""),
    port(6379, "Redis", "infra", world.infra ? 1180 : null, "ssh (Colima port forwarding)", ""),
    port(7233, "Temporal", "infra", world.infra ? 1180 : null, "ssh (Colima port forwarding)", ""),
    port(
      8000,
      "product public listener",
      "product",
      world.product.public ? 62110 : null,
      "cw-mvp serve",
      "make product",
    ),
    ...SERVICES.map((name, index) =>
      port(
        8001 + index,
        name,
        "UI-only stack",
        index < world.services ? 41201 + index : null,
        `uvicorn ${name.replace(/-/g, "_")}.main:app`,
        "make web-stack",
      ),
    ),
    port(
      8080,
      "product internal listener",
      "product",
      world.product.internal ? 62110 : null,
      "cw-mvp serve",
      "make product",
    ),
    port(
      8081,
      "product worker health",
      "product",
      world.product.worker ? 62150 : null,
      "cw-mvp worker",
      "make product",
    ),
    port(
      8233,
      "Temporal UI",
      "infra",
      world.infra ? 1180 : null,
      "ssh (Colima port forwarding)",
      "",
    ),
    port(
      19092,
      "Kafka API (Redpanda)",
      "infra",
      world.infra ? 1180 : null,
      "ssh (Colima port forwarding)",
      "",
    ),
  ];
  const MODULES = { profile: "profile_service", eval: "eval_service" };
  // the processes as the demo helper lists them: the services' group, the web app, Claude's
  // build agent's make check, this window's helper, and (here only) another control window
  const proc = (pid, pgid, ppid, elapsed, command, origin) => ({
    pid,
    pgid,
    ppid,
    elapsed,
    command,
    origin,
    kind: origin.startsWith("this panel") ? "this-app" : "other",
  });
  const processes = [];
  SERVICES.slice(0, world.services).forEach((name, index) =>
    processes.push(
      proc(
        41201 + index,
        41200,
        41200,
        2710,
        `uvicorn ${MODULES[name] ?? name.replace(/-/g, "_")}.main:app`,
        "make web-stack",
      ),
    ),
  );
  if (world.web) {
    processes.push(
      proc(76165, 76165, 1, 2650, "pnpm --filter web dev", "panel web app"),
      proc(76180, 76165, 76165, 2648, "next-server (v16.3.8)", "panel web app"),
    );
  }
  for (const session of world.sessions) {
    // what Claude Code runs is named, never stopped from here; a terminal's make check may be
    const who = session.kind === "agent" ? "run by Claude Code" : "other";
    processes.push(
      proc(session.pid, session.pid, 1, session.elapsed, session.label, who),
      proc(
        session.pid + 1,
        session.pid,
        session.pid,
        session.elapsed,
        "bash -c uv run pytest",
        who,
      ),
      proc(
        session.pid + 2,
        session.pid,
        session.pid + 1,
        session.elapsed - 1,
        "uv run pytest -m not integration",
        who,
      ),
      proc(
        session.pid + 3,
        session.pid,
        session.pid + 2,
        session.elapsed - 2,
        "pytest -m not integration --cov",
        who,
      ),
    );
  }
  processes.push(proc(70000, 70000, 1, 600, "panel_server.py", "this panel (the window)"));
  processes.push(
    proc(
      5120,
      5120,
      1,
      86400,
      "python3 tools/control-panel/control_panel.py",
      "control panel 5120",
    ),
  );
  return { taken_at: Date.now() / 1000, ports, processes, error: "" };
}

/** What a stop of pid may signal, with panel_core's refusals and words (stop_options). */
export function stopPreviewOf(world, pid) {
  const all = processesOf(world).processes;
  const proc = all.find((p) => p.pid === pid);
  const refused = (reason) => ({
    options: [{ mode: "none", pgid: proc?.pgid ?? 0, text: "", pids: [], refused: reason }],
    warnings: [],
  });
  if (!proc) return refused(`pid ${pid} is not running`);
  if (proc.origin === "this panel (the window)")
    return refused("that is this control panel or what started it");
  if (proc.origin.startsWith("control panel"))
    return refused("that is a control panel window; close it from the window itself");
  if (proc.origin.startsWith("run by "))
    return refused(`${proc.origin.slice("run by ".length)} runs it; stop it there`);
  const view = (p) => ({ pid: p.pid, command: p.command, origin: p.origin });
  const lines = (list) => list.map((p) => `  ${p.pid}  ${p.command}  [${p.origin}]`);
  const group = all.filter((p) => p.pgid === proc.pgid);
  const descendants = (root) =>
    all.filter((p) => p.ppid === root).flatMap((child) => [child, ...descendants(child.pid)]);
  const tree = [proc, ...descendants(proc.pid)];
  const options = [
    {
      mode: "group",
      pgid: proc.pgid,
      text: [
        `Send SIGTERM to process group ${proc.pgid} (${group.length} processes):`,
        ...lines(group),
      ].join("\n"),
      pids: group.map(view),
      refused: "",
    },
  ];
  if (tree.length !== group.length) {
    options.push({
      mode: "tree",
      pgid: proc.pgid,
      text: [
        `Send SIGTERM to pid ${proc.pid} and its children (${tree.length}):`,
        ...lines(tree),
      ].join("\n"),
      pids: tree.map(view),
      refused: "",
    });
  }
  const others = options.some((o) => o.pids.some((p) => !p.origin.startsWith("this panel")));
  return {
    options,
    warnings: others
      ? [
          {
            code: "sessions",
            message:
              "This app did not start every one of these. Another session may be using them, for example a make check in a terminal or Claude's build agent.",
          },
        ]
      : [],
  };
}

export function logSourcesOf() {
  const sources = [
    ...SERVICES.map((name) => ({
      kind: "file",
      exists: true,
      id: `web-stack:${name}`,
      label: name,
      group: "Services",
      path: `var/web-stack/${name}.log`,
    })),
    { id: "web-stack:web", label: "Web app", group: "Web app", path: "var/web-stack/web.log" },
    { id: "product:app", label: "App", group: "The product", path: "var/product/app.log" },
    {
      id: "product:worker",
      label: "Worker",
      group: "The product",
      path: "var/product/worker.log",
    },
    { id: "product:web", label: "Web app", group: "The product", path: "var/product/web.log" },
    {
      id: "container:postgres",
      label: "Postgres",
      group: "Containers",
      path: "docker compose logs postgres",
    },
    {
      id: "container:redpanda",
      label: "Redpanda",
      group: "Containers",
      path: "docker compose logs redpanda",
    },
    {
      id: "container:temporal",
      label: "Temporal",
      group: "Containers",
      path: "docker compose logs temporal",
    },
  ];
  return {
    sources: sources.map((source) => ({
      kind: source.id.startsWith("container:") ? "container" : "file",
      exists: true,
      ...source,
    })),
  };
}

export function logOf(id, tail) {
  const lines = [];
  const now = Date.parse("2026-10-06T14:00:00Z");
  for (let i = 0; i < Math.min(tail, 140); i += 1) {
    const stamp = new Date(now + i * 2000).toISOString().replace("T", " ").slice(0, 19);
    if (i === 0) lines.push(`${stamp} INFO: Started server process [60100]`);
    else if (i % 37 === 0)
      lines.push(`${stamp} WARNING: slow request GET /v1/rulebook/rules 812 ms`);
    else lines.push(`${stamp} INFO: 127.0.0.1 - "GET /health HTTP/1.1" 200 OK`);
  }
  const source = logSourcesOf().sources.find((item) => item.id === id);
  return {
    id,
    label: source?.label ?? id,
    taken_at: Date.now() / 1000,
    error: "",
    lines,
    truncated: tail < 140,
    path: logSourcesOf().sources.find((s) => s.id === id)?.path ?? "",
  };
}

export function kafkaOf(world) {
  if (!world.infra) {
    return {
      taken_at: Date.now() / 1000,
      groups: [],
      topics: [],
      error: "groups: Docker is not running",
      next_in: 0,
    };
  }
  return {
    taken_at: Date.now() / 1000,
    groups: [
      { group: "applicability-engine.profiles", state: "Stable", members: 1, total_lag: 0 },
      { group: "applicability-engine.rules", state: "Stable", members: 1, total_lag: 0 },
      { group: "notification.obligations", state: "Stable", members: 1, total_lag: 12 },
      { group: "obligation.decisions", state: "Stable", members: 1, total_lag: 3 },
      { group: "obligation.rules", state: "Empty", members: 0, total_lag: 0 },
    ],
    topics: [
      { name: "applicability.decided", partitions: 1, messages: 214 },
      { name: "document.discovered", partitions: 1, messages: 0 },
      { name: "obligation.closed", partitions: 1, messages: 18 },
      { name: "obligation.created", partitions: 1, messages: 96 },
      { name: "obligation.created.dlq", partitions: 1, messages: 2, dead_letters: true },
      { name: "obligation.due_soon", partitions: 1, messages: 7 },
      { name: "profile.updated", partitions: 1, messages: 41 },
      { name: "rule.published", partitions: 1, messages: 4 },
    ],
    error: "",
    next_in: 0,
  };
}

export const DOCS = {
  docs: [
    {
      id: "local-dev",
      label: "Local development",
      path: "docs/onboarding/local-dev.md",
      kind: "doc",
    },
    { id: "product", label: "The local product", path: "docs/onboarding/product.md", kind: "doc" },
    { id: "demo", label: "The five-minute demo", path: "docs/onboarding/demo.md", kind: "doc" },
    {
      id: "control-panel",
      label: "This app",
      path: "docs/onboarding/control-panel.md",
      kind: "doc",
    },
    { id: "runbooks", label: "Runbooks", path: "docs/runbooks", kind: "folder" },
  ],
};

export function githubOf(world) {
  const base = "https://github.com/himanshudixit2002/compliancewatch";
  const links = [
    { label: "Pull requests", url: `${base}/pulls` },
    { label: "Actions", url: `${base}/actions` },
    { label: "Repository", url: base },
  ];
  if (world.branch !== "main") {
    links.push({ label: `Branch ${world.branch}`, url: `${base}/tree/${world.branch}` });
    links.push({ label: "Compare with main", url: `${base}/compare/main...${world.branch}` });
  }
  return {
    available: false,
    reason: "The GitHub CLI (gh) is not signed in, so pull requests and CI are not read.",
    links,
    prs: [],
  };
}

// ---- what a run prints -------------------------------------------------------------------------

export function outputFor(label, index) {
  const text = label.toLowerCase();
  if (text.includes("docker")) return ["Docker is already running"];
  if (text.includes("databases and queues") || text === "make dev")
    return [
      "docker compose up -d --wait postgres redis redpanda temporal temporal-ui",
      " Container compliancewatch-postgres-1  Healthy",
      " Container compliancewatch-redis-1  Healthy",
      " Container compliancewatch-redpanda-1  Healthy",
      " Container compliancewatch-temporal-1  Healthy",
      "Postgres localhost:5432 · Redis localhost:6379 · Kafka localhost:19092 · Temporal UI http://localhost:8233",
    ];
  if (text.includes("migrate"))
    return SERVICES.slice(0, 6).map(
      (s) => `${s}: INFO  [alembic.runtime.migration] Running upgrade -> head`,
    );
  if (text.includes("start services") || text.includes("web-stack"))
    return [
      "web stack: services on 8001-8010, postgres stores, billing provider none, rulebook publishing on",
      ...SERVICES.slice(0, 4).map((s, i) => `started ${s} on ${8001 + i}`),
    ];
  if (text.includes("wait"))
    return ["waiting for every /health ...", "all 10 services answer /health"];
  if (text.includes("web app"))
    return [
      "web app started (pid 61000, log var/web-stack/web.log)",
      "web app ready on http://localhost:3000",
    ];
  if (text.startsWith("open")) return [];
  if (text.includes("check"))
    return ["▸ health ... ok", "▸ honesty ... ok", "▸ loop ... ok", "13 passed, 1 skipped"];
  return [`${label}: step ${index + 1} done`];
}

export { MAKE_HELP };
