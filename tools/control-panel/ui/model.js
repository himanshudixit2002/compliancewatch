// What the window makes of the helper's answers: every payload is normalised here, once, into
// the shapes the views read, and the derived facts (what each part is doing, what a confirm
// must warn about, why a run failed) are worked out here too.

import { formatElapsed, sentence, stepLabel } from "./dom.js";

const bool = (value) => (value === null || value === undefined ? null : Boolean(value));
const num = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value) => (value === null || value === undefined ? "" : String(value));
const list = (value) => (Array.isArray(value) ? value : []);

/** The five containers "make dev" starts; the Databases pill counts these. */
export const CORE_INFRA = ["postgres", "redis", "redpanda", "temporal", "temporal-ui"];

function endpoint(raw, fallbackPort) {
  if (raw === null || raw === undefined) return { up: null, port: fallbackPort, url: "" };
  if (typeof raw === "boolean") return { up: raw, port: fallbackPort, url: "" };
  return { up: bool(raw.up), port: num(raw.port) ?? fallbackPort, url: str(raw.url), pid: raw.pid };
}

export function normalizeStatus(raw) {
  const s = raw ?? {};
  const infraSource = Array.isArray(s.infra) ? s.infra : list(s.infra?.containers ?? s.containers);
  const infra = infraSource.map((c) => ({
    service: str(c.service ?? c.name),
    label: str(c.label ?? c.what ?? c.service ?? c.name),
    // "core" (API.md) and "" both mean the containers make dev starts
    profile: str(c.profile) === "core" ? "" : str(c.profile),
    state: str(c.state),
    health: str(c.health),
    exitCode: num(c.exit_code) ?? 0,
    up:
      c.up === undefined
        ? c.state === "running" && ["", "healthy"].includes(str(c.health))
        : !!c.up,
    ports: list(c.ports),
  }));
  const services = list(s.services).map((svc) => ({
    name: str(svc.name),
    port: num(svc.port),
    up: bool(svc.up),
    url: str(svc.url) || (num(svc.port) ? `http://localhost:${svc.port}` : ""),
  }));
  const product = s.product ?? {};
  const checkout = s.checkout ?? s.git ?? {};
  const branch = str(checkout.branch);
  return {
    takenAt: num(s.taken_at),
    demo: Boolean(s.demo),
    summary: str(s.summary),
    docker: {
      up: bool(typeof s.docker === "object" && s.docker !== null ? s.docker.up : s.docker),
      detail: str(s.docker?.detail),
    },
    infra,
    services,
    web: endpoint(s.web, 3000),
    product: {
      internal: endpoint(product.internal, 8080),
      public: endpoint(product.public, 8000),
      worker: endpoint(product.worker, 8081),
      web: endpoint(product.web, 3400),
    },
    background: list(s.background).map((b) => ({
      key: str(b.key),
      label: str(b.label),
      kind: str(b.kind) || (str(b.key).startsWith("relay") ? "relay" : "worker"),
      service: str(b.service) || str(b.key).replace(/^(worker|relay)-/, ""),
      pid: num(b.pid),
    })),
    checkout: {
      branch,
      sha: str(checkout.sha),
      subject: str(checkout.subject),
      when: str(checkout.when),
      dirty: num(checkout.dirty) ?? 0,
      ahead: num(checkout.ahead),
      behind: num(checkout.behind),
      isMain: checkout.is_main === undefined ? branch === "main" : Boolean(checkout.is_main),
      error: str(checkout.error),
    },
    sessions: list(s.sessions ?? s.foreign).map((item) =>
      typeof item === "string"
        ? { pid: null, label: item, text: item, elapsed: null, kind: "other" }
        : {
            pid: num(item.pid),
            label: str(item.label ?? item.command ?? item.text),
            text: str(item.text ?? item.label),
            elapsed: num(item.elapsed),
            kind: str(item.kind) || "other",
          },
    ),
  };
}

export const SAFETY = {
  safe: {
    label: "Safe",
    tone: "success",
    icon: "shield",
    plain: "Starts or reads things. Nothing is lost.",
  },
  "changes-data": {
    label: "Changes data",
    tone: "info",
    icon: "database",
    plain: "Writes to your local databases or files.",
  },
  "stops-things": {
    label: "Stops things",
    tone: "warning",
    icon: "stop",
    plain: "Stops running parts. Anything using them is interrupted.",
  },
  destructive: {
    label: "Deletes data",
    tone: "danger",
    icon: "trash",
    plain: "Removes local data. You are always asked first.",
  },
  refused: {
    label: "Never runs here",
    tone: "neutral",
    icon: "shield-off",
    plain: "This app never runs it; the reason says why.",
  },
};

export function safetyOf(value) {
  const key = str(value).replace(/_/g, "-").toLowerCase();
  return SAFETY[key] ? key : "safe";
}

function normalizeParam(p) {
  const choices = list(p.choices ?? p.options).map((c) =>
    typeof c === "object" && c !== null
      ? { value: str(c.value), label: str(c.label ?? c.value), note: str(c.note) }
      : { value: str(c), label: str(c), note: "" },
  );
  const type = str(p.kind ?? p.type) || (choices.length ? "choice" : "text");
  const required = p.required !== false && type !== "boolean";
  // an optional choice can be left empty ("Leave empty to run every step"): offer that first
  if (type === "choice" && !required && !choices.some((c) => c.value === "")) {
    const every = { step: "Every step", service: "Every service" }[str(p.name)] ?? "Any";
    choices.unshift({ value: "", label: every, note: "" });
  }
  return {
    name: str(p.name),
    label: str(p.label ?? p.name),
    type,
    choices,
    default: p.default ?? (type === "boolean" ? false : required ? (choices[0]?.value ?? "") : ""),
    required,
    help: str(p.help),
  };
}

export function normalizeAction(a) {
  const what = a.what_happens ?? a.whatHappens ?? a.what ?? [];
  return {
    id: str(a.id),
    title: /^make\s/.test(str(a.title)) ? str(a.title) : sentence(a.title),
    summary: str(a.summary ?? a.plain),
    whatHappens: Array.isArray(what) ? what.map(str) : str(what) ? [str(what)] : [],
    duration: str(a.duration),
    group: str(a.group),
    safety: safetyOf(a.safety),
    confirm: a.confirm ? str(a.confirm) : "",
    enabled: a.enabled !== false,
    reason: str(a.reason ?? a.disabled_reason),
    fixAction: str(a.fix_action),
    kind: str(a.kind) || "step",
    preview: Boolean(a.preview),
    needsConfirm:
      a.needs_confirm === undefined ? safetyOf(a.safety) !== "safe" : Boolean(a.needs_confirm),
    button: str(a.button),
    params: list(a.params).map(normalizeParam),
    steps: list(a.steps).map((step) => (typeof step === "string" ? step : str(step.label))),
    command: Array.isArray(a.command) ? a.command.join("\n") : str(a.command),
    url: str(a.url),
    source: str(a.source) || "curated",
    // a make entry that a curated action already covers names it (make:dev-down: databases-stop)
    coveredBy: str(a.covered_by),
    keywords: str(a.keywords),
  };
}

export function normalizeActions(raw) {
  const actions = list(raw?.actions ?? raw).map(normalizeAction);
  const groups = list(raw?.groups).map((g) =>
    typeof g === "string"
      ? { id: g, title: sentence(g), summary: "" }
      : { id: str(g.id), title: str(g.title ?? g.id), summary: str(g.summary) },
  );
  return { actions, groups };
}

/** The verb on an action's main button. */
export function buttonLabel(action) {
  if (action.button) return action.button;
  if (action.kind === "open") return "Open";
  const first = action.title.split(" ")[0];
  return ["Start", "Stop", "Restart", "Open", "Load", "Back", "Restore", "Reset", "Wait"].includes(
    first,
  )
    ? first === "Back"
      ? "Back up"
      : first
    : "Run";
}

export function normalizeStep(step) {
  if (typeof step === "string") return { label: step, state: "pending", seconds: null };
  return {
    label: str(step.label),
    state: str(step.state) || "pending",
    seconds: num(step.seconds),
  };
}

export function normalizeRun(raw) {
  const r = raw ?? {};
  const state = str(r.state) || (r.ok === true ? "ok" : r.cancelled ? "cancelled" : "running");
  return {
    id: str(r.run_id ?? r.id),
    actionId: str(r.action_id ?? r.action),
    kind: str(r.kind),
    title: sentence(r.title),
    state,
    startedAt: num(r.started_at),
    finishedAt: num(r.finished_at),
    seconds: num(r.seconds),
    steps: list(r.steps ?? r.results).map(normalizeStep),
    error: r.error ? normalizeError(r.error) : null,
    lines: list(r.lines).map(normalizeLine),
    params: r.params ?? {},
  };
}

export function normalizeLine(line) {
  if (typeof line === "string") return { text: line, tag: null };
  return { text: str(line?.text), tag: line?.tag ? str(line.tag) : null };
}

export function normalizeError(e) {
  if (typeof e === "string") return { title: e, fix: "", action: "", detail: "", code: "" };
  return {
    code: str(e.code),
    title: str(e.message ?? e.title),
    fix: str(e.fix),
    action: str(e.action ?? e.action_id),
    detail: str(e.detail),
  };
}

// ---- what each part of the stack is doing --------------------------------------------------

export const PART_STATE_LABEL = {
  running: "Running",
  partial: "Partly running",
  stopped: "Stopped",
  problem: "Needs attention",
  unknown: "Checking",
  busy: "Working",
};

const BUSY_WORDS = [
  [/docker|colima/i, "docker"],
  [/databases|queues|dev-down|\bmake dev\b|migrat|seed/i, "infra"],
  [/services|web-stack|ui-only/i, "services"],
  [/web app|open http/i, "web"],
  [/product/i, "product"],
];

const ACTION_PARTS = {
  "docker-start": "docker",
  "docker-stop": "docker",
  "databases-start": "infra",
  "databases-stop": "infra",
  "ui-start": "services",
  "ui-stop": "services",
  "ui-restart": "services",
  "ui-wait": "services",
  "web-start": "web",
  "web-stop": "web",
  "product-start": "product",
  "product-stop": "product",
  "product-wait": "product",
  "product-image": "product",
  "product-image-down": "product",
};

/** The part a running step is working on, and whether it is starting or stopping it. */
export function busyPart(run) {
  if (!run || run.state !== "running") return null;
  const stopping = /stop|down|reset/i.test(run.actionId);
  let part = ACTION_PARTS[run.actionId] ?? null;
  if (!part) {
    const current = run.steps.find((step) => step.state === "running");
    const label = current?.label ?? "";
    part = BUSY_WORDS.find(([pattern]) => pattern.test(label))?.[1] ?? null;
  }
  return part ? { part, stopping } : null;
}

function rollup(states) {
  const known = states.filter((s) => s !== null);
  if (!known.length) return "unknown";
  const up = known.filter(Boolean).length;
  if (up === known.length) return "running";
  if (up === 0) return "stopped";
  return "partial";
}

/** What each part is doing, for the pills, the Home diagram and the hero. */
export function partsOf(status, run) {
  const busy = busyPart(run);
  const mark = (key, part) => {
    if (busy?.part === key) {
      return {
        ...part,
        state: "busy",
        label: busy.stopping ? "Stopping" : "Starting",
        stopping: busy.stopping,
      };
    }
    return part;
  };
  if (!status) {
    const unknown = { state: "unknown", label: PART_STATE_LABEL.unknown, detail: "" };
    return {
      docker: unknown,
      infra: { ...unknown, items: [] },
      services: { ...unknown, items: [], up: 0, total: 10 },
      web: { ...unknown, url: "" },
      product: { ...unknown, items: [], url: "" },
    };
  }
  const docker =
    status.docker.up === null
      ? { state: "unknown", label: PART_STATE_LABEL.unknown, detail: "" }
      : status.docker.up
        ? { state: "running", label: "Running", detail: status.docker.detail || "Docker answers" }
        : { state: "stopped", label: "Stopped", detail: "Docker is not running" };

  const core = CORE_INFRA.map((name) => {
    const c = status.infra.find((item) => item.service === name);
    let state = "stopped";
    if (c?.up) state = "running";
    else if (c && (c.health === "unhealthy" || c.state === "restarting")) state = "problem";
    else if (c && c.state === "exited" && c.exitCode !== 0) state = "problem";
    else if (c && c.state === "running") state = "busy";
    return { name, label: c?.label || name, state };
  });
  const coreUp = core.filter((c) => c.state === "running").length;
  let infraState = rollup(core.map((c) => c.state === "running"));
  if (core.some((c) => c.state === "problem")) infraState = "problem";
  if (!status.docker.up && status.docker.up !== null) infraState = "stopped";
  const infra = {
    state: infraState,
    label: infraState === "partial" ? `${coreUp} of ${core.length}` : PART_STATE_LABEL[infraState],
    detail: `${coreUp} of ${core.length} running`,
    items: core,
  };

  const servicesUp = status.services.filter((s) => s.up).length;
  const servicesState = status.services.length
    ? rollup(status.services.map((s) => s.up))
    : "unknown";
  const services = {
    state: servicesState,
    label:
      servicesState === "partial"
        ? `${servicesUp} of ${status.services.length}`
        : PART_STATE_LABEL[servicesState],
    detail: `${servicesUp} of ${status.services.length} answering`,
    up: servicesUp,
    total: status.services.length,
    items: status.services,
  };

  const webState = status.web.up === null ? "unknown" : status.web.up ? "running" : "stopped";
  const web = {
    state: webState,
    label: PART_STATE_LABEL[webState],
    detail: `localhost:${status.web.port}`,
    url: status.web.url || `http://localhost:${status.web.port}`,
  };

  const p = status.product;
  const productItems = [
    { key: "internal", label: "App", port: p.internal.port, up: p.internal.up },
    { key: "worker", label: "Worker", port: p.worker.port, up: p.worker.up },
    { key: "web", label: "Web app", port: p.web.port, up: p.web.up },
  ];
  const productState = rollup(productItems.map((item) => item.up));
  const productUp = productItems.filter((item) => item.up).length;
  const product = {
    state: productState,
    label:
      productState === "partial"
        ? `${productUp} of ${productItems.length}`
        : PART_STATE_LABEL[productState],
    detail: `${productUp} of ${productItems.length} answering`,
    items: productItems,
    url: p.web.url || `http://127.0.0.1:${p.web.port}`,
  };

  return {
    docker: mark("docker", docker),
    infra: mark("infra", infra),
    services: mark("services", services),
    web: mark("web", web),
    product: mark("product", product),
  };
}

/** Home's headline: what the whole stack is doing. */
export function overallState(parts, run) {
  if (run?.state === "running") {
    if (run.actionId === "start-everything") return "starting";
    if (run.actionId === "stop-everything") return "stopping";
  }
  const apps = [parts.services.state, parts.web.state, parts.product.state];
  if (parts.web.state === "running" && parts.services.state === "running") return "running";
  if (parts.product.state === "running") return "running";
  if (
    apps.some((s) => s === "running" || s === "partial") ||
    parts.infra.state === "running" ||
    parts.infra.state === "partial" ||
    parts.docker.state === "running"
  ) {
    return "partial";
  }
  if (parts.docker.state === "unknown") return "unknown";
  return "stopped";
}

// ---- the checkout and other sessions -------------------------------------------------------

export function describeSession(session) {
  const time = session.elapsed !== null ? `, ${formatElapsed(session.elapsed)}` : "";
  const pid = session.pid ? `pid ${session.pid}` : "";
  const what = session.label || session.text;
  const where = [pid, time.replace(/^, /, "")].filter(Boolean).join(", ");
  const tail = where ? ` (${where})` : "";
  if (session.kind === "agent") return `Claude's build agent is running ${what}${tail}`;
  if (session.kind === "terminal") return `A terminal is running ${what}${tail}`;
  if (session.kind === "panel") return `Another control window is open${tail}`;
  return session.text && !where ? session.text : `${what}${tail}`;
}

/** What a confirm warns about: a branch other than main, and other sessions at work. */
export function checkoutWarnings(status) {
  const warnings = [];
  if (!status) return warnings;
  const { checkout, sessions } = status;
  if (checkout.branch && !checkout.isMain) {
    warnings.push({
      kind: "branch",
      tone: "warning",
      title: `The checkout is on ${checkout.branch}, not main`,
      body: "This runs that branch's code and commands. That is right when you are trying the branch; if you meant main, switch the checkout to main first.",
    });
  }
  if (sessions.length) {
    warnings.push({
      kind: "sessions",
      tone: "danger",
      title:
        sessions.length === 1
          ? "Another session is working in this checkout"
          : `${sessions.length} other sessions are working in this checkout`,
      body: "If this stops or changes what they use, their work fails. Wait for them to finish if you can.",
      items: sessions.map(describeSession),
    });
  }
  return warnings;
}

// ---- why a run failed, in plain words -------------------------------------------------------

const FAILURES = [
  {
    test: /cannot connect to the docker daemon|is the docker daemon running|docker daemon is not running|error during connect/i,
    title: "Docker is not running",
    fix: "The databases run inside Docker. Start Docker, then try again.",
    action: "docker-start",
  },
  {
    test: /colima: (command )?not found|no such file or directory: '?colima/i,
    title: "Colima is not installed",
    fix: "This app starts Docker with Colima. Install it (the Local development guide says how) or start Docker Desktop yourself.",
    action: "doctor",
  },
  {
    test: /address already in use|port is already allocated|a port is in use/i,
    title: "A port is already in use",
    fix: "Something else is using a port this needs. Processes shows who holds each port; stop it there if it is this project's, or change the port in .env.",
    go: "#/processes",
  },
  {
    test: /is not a target of this checkout's makefile|no rule to make target/i,
    title: "This branch does not have that command",
    fix: "The checkout is on a branch whose Makefile lacks it. Switch the checkout to main in a terminal, or ask whoever works on that branch.",
  },
  {
    test: /the product does not answer|product-seed runs only against the running product/i,
    title: "The product is not running",
    fix: "Start the product, wait until it is ready, then try again.",
    action: "product-start",
  },
  {
    test: /role "cw_app" does not exist|permission denied for (schema|table)/i,
    title: "The product's database role is missing",
    fix: "Refresh the product's database role, then try again.",
    action: "product-role",
  },
  {
    test: /is not a dump pg_restore can read/i,
    title: "That backup cannot be read",
    fix: "Pick another backup, or make a new one with Back up now.",
  },
  {
    test: /^error: refused:|\brefused: /im,
    title: "This app refused to run it",
    fix: 'It would break one of the safety rules in the Guide\'s "What this app will never do".',
    go: "#/guide/never",
  },
  {
    test: /did not become healthy|health-?check timeout|unhealthy/i,
    title: "A database did not become healthy",
    fix: "Docker may be short of memory. Stop everything, then start again. Logs shows each container's own log.",
    go: "#/logs",
  },
  {
    test: /still running after .*; stopped/i,
    title: "It took too long and was stopped",
    fix: "Try again. If it keeps happening, read its log in Logs.",
  },
  {
    test: /(uv|pnpm|docker|node|make|colima): (command )?not found|cannot run \w+: no such file/i,
    title: "A tool this needs is missing",
    fix: "Check which tools are installed to see what is missing.",
    action: "doctor",
  },
];

/** The plain reason a run failed, with a fix and the action that applies it when there is one. */
export function explainFailure(run, lines = []) {
  if (!run) return null;
  if (run.state === "cancelled") {
    return {
      title: "Cancelled",
      fix: "The step that was running was stopped, and the steps after it did not run.",
      action: "",
      go: "",
      detail: "",
    };
  }
  if (run.state !== "failed") return null;
  const tail = lines.slice(-80).map((line) => line.text);
  const detailLines = tail
    .filter((text) => /error|fail|refused|cannot|not found|denied/i.test(text))
    .slice(-12);
  const detail = (detailLines.length ? detailLines : tail.slice(-12)).join("\n");
  // The helper's own reading wins when it says something specific (a fix, an action, a code
  // of its own); a generic "it did not finish" leaves the window to read the lines itself.
  const specific =
    run.error?.title && (run.error.action || !["", "failed"].includes(run.error.code));
  if (specific) {
    return { go: "", ...run.error, detail: run.error.detail || detail };
  }
  const timedOut = run.steps.find((step) => step.state === "timeout");
  if (timedOut && /colima stop/i.test(timedOut.label)) {
    return {
      title: "Docker did not stop in time",
      fix: "Colima did not finish stopping. You can force it to stop; that is a separate question, because a forced stop gives the databases no time to close their files.",
      action: "force-stop-docker",
      go: "",
      detail,
    };
  }
  if (timedOut) {
    return {
      title: `"${stepLabel(timedOut.label)}" took too long and was stopped`,
      fix: "This step has a time limit, and it ran past it. Try again; if it keeps happening, read its output or its log in Logs.",
      action: "",
      go: "",
      detail,
    };
  }
  const text = tail.join("\n");
  const match = FAILURES.find((failure) => failure.test.test(text));
  const failedStep = run.steps.find((step) => step.state === "failed");
  if (match) {
    return {
      title: match.title,
      fix: match.fix,
      action: match.action ?? "",
      go: match.go ?? "",
      detail,
    };
  }
  if (/^gate|check|^product-e2e/.test(run.actionId)) {
    return {
      title: `${run.title}: it did not pass`,
      fix: "Its output says what failed. Fix that, then run the check again.",
      action: "",
      go: "",
      detail,
    };
  }
  return {
    title: failedStep ? `It stopped at "${stepLabel(failedStep.label)}"` : `${run.title} failed`,
    fix: "The last lines of its output say why. Show technical details for them, or open the whole output.",
    action: "",
    go: "",
    detail,
  };
}

/** Progress through a run's steps, 0 to 1, with the step in words. */
export function runProgress(run) {
  const total = run.steps.length;
  if (!total) return { value: null, index: 0, total: 0, label: "" };
  const done = run.steps.filter((s) =>
    ["ok", "failed", "timeout", "cancelled", "skipped"].includes(s.state),
  );
  const current = run.steps.findIndex((s) => s.state === "running");
  const index = current >= 0 ? current : Math.min(done.length, total - 1);
  const value = (done.length + (current >= 0 ? 0.35 : 0)) / total;
  const label = run.steps[index] ? stepLabel(run.steps[index].label) : "";
  return { value: Math.min(1, value), index, total, label };
}
