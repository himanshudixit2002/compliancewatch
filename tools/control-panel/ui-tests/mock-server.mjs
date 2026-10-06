#!/usr/bin/env node
// A stand-in for panel_server.py that speaks its API (tools/control-panel/API.md), for
// developing the window and for its Playwright tests when the real helper is not wanted. It
// serves ../ui and answers with made-up data: no program runs and nothing is signalled. It is
// never part of the app.
//
//   node tools/control-panel/ui-tests/mock-server.mjs [--port 0] [--first-launch] [--speed 1]
//
// It binds 127.0.0.1, prints {"port": ..., "token": ...} on one line, and checks the token, the
// Host header and any Origin header as the helper does. As the helper, it gives single-use launch
// codes (POST /api/launch-code) that a window swaps for the token once (POST /api/launch). POST /__mock/state (token required)
// sets the made-up world for a test: which parts run, the branch, other sessions, a failure for
// the next run, the prefs and the speed of runs.

import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  AGENT_SESSION,
  baseWorld,
  CURATED,
  DOCS,
  featuresOf,
  flagsOf,
  GROUPS,
  githubOf,
  kafkaOf,
  logOf,
  logSourcesOf,
  makeActions,
  outputFor,
  processesOf,
  statusOf,
  stopPreviewOf,
} from "./fixtures.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const UI = resolve(here, "..", "ui");
const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const index = args.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const next = args[index + 1];
  return next && !next.startsWith("--") ? next : true;
};

const given = flag("token", "");
const TOKEN = typeof given === "string" && given ? given : randomBytes(32).toString("base64url");
let speed = Number(flag("speed", 1)) || 1;
let world = baseWorld();
let prefs = { tour_done: !flag("first-launch", false), last_view: "", dismissed: [] };
let failNext = null;
let eventId = 0;
const clients = new Set();
const runs = [];
let runCounter = 0;
let generation = 0;
let port = 0;
let lastKafka = null;
let featuresRead = false;
let kafkaStartedAt = 0;

if (flag("scenario", "") === "running") {
  Object.assign(world, { docker: true, infra: true, services: 10, web: true });
}
if (flag("demo", false)) world.demo = true;

// ---- the catalog --------------------------------------------------------------------------------

function enabledFor(action) {
  const needs = action.needs;
  if (!needs) return true;
  if (needs === "docker") return world.docker;
  if (needs === "product") return world.product.internal;
  if (needs === "services") return world.services === 10;
  if (needs === "infra") return world.infra;
  return true;
}

function catalog() {
  const actions = [...CURATED, ...makeActions()].map((a) => {
    const refused = a.enabled === false;
    const enabled = !refused && enabledFor(a);
    const safety = refused ? "refused" : a.safety;
    return {
      kind: "step",
      source: "curated",
      confirm: null,
      what_happens: [],
      url: null,
      ...a,
      safety,
      needs_confirm: safety !== "safe" && safety !== "refused",
      params: (a.params ?? []).map(({ type, ...p }) => ({
        kind: type ?? "choice",
        required: true,
        ...p,
      })),
      enabled,
      reason: enabled ? "" : a.reason || a.reasonOff || "Not available now.",
      fix_action: enabled ? null : (a.fix_action ?? null),
    };
  });
  return { groups: GROUPS, actions };
}

let lastEnabled = "";
function catalogChanged() {
  const shape = catalog()
    .actions.map((a) => `${a.id}:${a.enabled}`)
    .join("|");
  if (shape === lastEnabled) return false;
  lastEnabled = shape;
  return true;
}
catalogChanged();

// ---- events -------------------------------------------------------------------------------------

function send(res, type, data) {
  eventId += 1;
  res.write(`id: ${eventId}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
}

function broadcast(type, data) {
  if (data?.run_id && runs.every((run) => run.run_id !== data.run_id)) return;
  for (const res of clients) send(res, type, data);
}

function worldChanged() {
  broadcast("status", statusOf(world));
  broadcast("processes", { taken_at: Date.now() / 1000 });
  if (catalogChanged()) broadcast("actions", {});
}

// ---- previews and confirm tokens ------------------------------------------------------------------

const tokens = new Map();
const canonical = (params) =>
  JSON.stringify(
    Object.keys(params ?? {})
      .sort()
      .map((key) => [key, params[key]]),
  );

function issue(binding) {
  const token = `c-${randomBytes(9).toString("base64url")}`;
  tokens.set(token, { ...binding, expires: Date.now() + 120000 });
  return token;
}

function redeem(token, binding) {
  const held = tokens.get(token);
  tokens.delete(token);
  return Boolean(
    held &&
    held.expires > Date.now() &&
    held.action === binding.action &&
    held.params === binding.params,
  );
}

/** The question an action asks first, with today's warnings, worded as panel_server.py does. */
function previewOf(action, params) {
  const base = { action_id: action.id, params, steps: action.steps ?? [], command: action.command };
  if (!action.needs_confirm) return { ...base, confirm: null, confirm_token: null, expires_in: 0 };
  const warnings = [];
  const changes = action.migrates || ["changes-data", "destructive"].includes(action.safety);
  if (changes && world.branch !== "main") {
    warnings.push({
      code: "not-main",
      tone: action.migrates ? "danger" : "warning",
      title: `This checkout is on ${world.branch}, not main`,
      message: `This checkout is on ${world.branch}, not main. ${
        action.migrates
          ? "This applies that branch's database changes to the shared development database. Other branches and sessions use the same database, and may fail until it is migrated back or reset."
          : "What this runs is that branch's code."
      }`,
      items: [],
    });
  }
  const takes = new Set(action.takes ?? []);
  if (action.migrates || action.safety === "destructive") takes.add("docker");
  const hit = world.sessions.filter((s) => s.uses.some((use) => takes.has(use)));
  if (hit.length) {
    const docker = takes.has("docker") && hit[0].uses.includes("docker");
    warnings.push({
      code: "sessions",
      tone: "danger",
      title: docker
        ? "Other sessions are using Docker's databases and queues"
        : "Other sessions are using the product",
      message: `${WHO[hit[0].kind]} is running ${hit[0].text} in this checkout. ${
        !docker
          ? "Stopping the product will break them."
          : action.migrates && !(action.takes ?? []).includes("docker")
            ? "Changing the database under them may break them."
            : "Stopping Docker or replacing its data will break them."
      }`,
      items: hit.map((s) => `${WHO[s.kind]}: ${s.text}`),
    });
  }
  if (action.rewrites && world.dirty) {
    warnings.push({
      code: "dirty",
      tone: "info",
      title: `${world.dirty} uncommitted ${world.dirty === 1 ? "file" : "files"}`,
      message: `This checkout has ${world.dirty} uncommitted ${world.dirty === 1 ? "file" : "files"}. This rewrites files in it; they show up as changed.`,
      items: [],
    });
  }
  const reaches =
    ["stop-everything", "web-stop"].includes(action.id) && world.web
      ? [
          { pid: 76165, command: "pnpm --filter web dev", origin: "panel web app" },
          { pid: 76180, command: "next-server (v16.3.8)", origin: "panel web app" },
        ]
      : [];
  return {
    ...base,
    confirm: {
      title: `${action.title}?`,
      text: action.confirm || action.summary,
      what_happens: action.what_happens,
      warnings,
      button: action.title,
      details: action.command,
      reaches,
    },
    reaches,
    confirm_token: issue({ action: action.id, params: canonical(params) }),
    expires_in: 120,
  };
}

// ---- the runner -----------------------------------------------------------------------------------

const PRODUCT_OFF = { internal: false, public: false, worker: false, web: false };
const EFFECTS = {
  "start-everything": [
    () => (world.docker = true),
    () => (world.infra = true),
    null,
    () => (world.services = 10),
    null,
    () => (world.web = true),
    null,
  ],
  "stop-everything": [
    () => (world.web = false),
    () => (world.services = 0),
    () => (world.product = { ...PRODUCT_OFF }),
    () => (world.background = {}),
    () => Object.assign(world, { infra: false, tools: false }),
    () => (world.docker = false),
  ],
  "docker-start": [() => (world.docker = true)],
  "docker-stop": [() => Object.assign(world, { docker: false, infra: false, tools: false })],
  "force-stop-docker": [() => Object.assign(world, { docker: false, infra: false, tools: false })],
  "databases-start": [() => Object.assign(world, { docker: true, infra: true })],
  "databases-stop": [() => Object.assign(world, { infra: false, tools: false })],
  "ui-start": [() => (world.services = 10), null],
  "ui-stop": [() => (world.services = 0)],
  "ui-restart": [() => (world.services = 0), () => (world.services = 10), null],
  "web-start": [() => (world.web = true)],
  "web-stop": [() => (world.web = false)],
  "product-start": [
    () => (world.docker = true),
    () =>
      Object.assign(world, {
        infra: true,
        product: { internal: true, public: true, worker: true, web: true },
      }),
  ],
  "product-stop": [() => (world.product = { ...PRODUCT_OFF })],
  "product-image": [
    () => (world.docker = true),
    () =>
      Object.assign(world, {
        infra: true,
        product: { internal: true, public: true, worker: true, web: false },
      }),
  ],
  "product-image-down": [() => (world.product = { ...PRODUCT_OFF })],
  "dev-observability": [() => (world.tools = true)],
  reset: [
    null,
    () => (world.services = 0),
    () => (world.product = { ...PRODUCT_OFF }),
    () => (world.background = {}),
    null,
    null,
    null,
    null,
  ],
};

function activeStep() {
  return runs.find((r) => r.state === "running" && r.kind !== "read");
}

function startRun(action, params) {
  runCounter += 1;
  const labels = action.steps?.length ? [...action.steps] : [action.title];
  if (action.id === "reset" && params.backup_first === false) labels.splice(0, 1);
  const run = {
    run_id: `r${runCounter}`,
    action_id: action.id,
    kind: action.kind ?? "step",
    title: action.title,
    params,
    state: "running",
    started_at: Date.now() / 1000,
    finished_at: null,
    seconds: 0,
    current_step: 0,
    steps: labels.map((label) => ({ label, state: "queued", seconds: 0 })),
    error: null,
    lines: [],
    cancel: false,
    generation,
  };
  runs.unshift(run);
  if (runs.length > 40) runs.pop();
  broadcast("run.started", {
    run_id: run.run_id,
    action_id: run.action_id,
    title: run.title,
    kind: run.kind,
    steps: labels,
    started_at: run.started_at,
  });
  simulate(run, action, params);
  return run;
}

const wait = (ms) => new Promise((done) => setTimeout(done, ms / speed));

function out(run, lines) {
  const items = lines.map((text) => ({
    text,
    tag: /error|fail|cannot|fatal/i.test(text) ? "err" : text.startsWith("▸") ? "step" : null,
  }));
  run.lines.push(...items);
  if (run.lines.length > 2000) run.lines.splice(0, run.lines.length - 2000);
  broadcast("run.output", { run_id: run.run_id, lines: items });
}

async function simulate(run, action, params) {
  const effects = EFFECTS[action.id] ?? [];
  let failed = false;
  for (let index = 0; index < run.steps.length; index += 1) {
    if (run.generation !== generation) return;
    const step = run.steps[index];
    if (run.cancel || failed) {
      step.state = run.cancel ? "cancelled" : "skipped";
      broadcast("run.step", {
        run_id: run.run_id,
        index,
        label: step.label,
        state: step.state,
        seconds: 0,
      });
      continue;
    }
    const started = Date.now();
    run.current_step = index;
    step.state = "running";
    broadcast("run.step", {
      run_id: run.run_id,
      index,
      label: step.label,
      state: "running",
      seconds: 0,
    });
    out(run, ["", `▸ ${step.label}`]);
    const failure =
      failNext && failNext.action === action.id && (failNext.step ?? 0) === index ? failNext : null;
    const lines = failure ? failure.lines : outputFor(step.label, index);
    const pause = action.id === "gate:check" || action.id === "product-check" ? 700 : 450;
    for (const line of lines) {
      await wait(pause / Math.max(lines.length, 1));
      if (run.cancel) break;
      out(run, [line]);
    }
    await wait(pause * 0.6);
    if (run.cancel) {
      step.state = "cancelled";
    } else if (failure) {
      failNext = null;
      step.state = failure.state ?? "failed";
      failed = true;
      const what = step.state === "timeout" ? "timed out" : "failed";
      const after = ((Date.now() - started) / 1000).toFixed(0);
      out(run, [`✗ ${step.label} ${what} after ${after} s — stopped here`]);
      if (failure.error) run.error = failure.error;
    } else {
      step.state = "ok";
      const effect = effects[index];
      if (effect) {
        effect();
        worldChanged();
      }
      const [kind, verb] = action.id.split("-");
      if ((kind === "worker" || kind === "relay") && verb === "start") {
        world.background[`${kind}-${params.service}`] = 70000 + Math.floor(Math.random() * 999);
        worldChanged();
      }
      if ((kind === "worker" || kind === "relay") && verb === "stop") {
        delete world.background[`${kind}-${params.service}`];
        worldChanged();
      }
    }
    step.seconds = (Date.now() - started) / 1000;
    broadcast("run.step", {
      run_id: run.run_id,
      index,
      label: step.label,
      state: step.state,
      seconds: step.seconds,
    });
  }
  if (run.generation !== generation) return;
  run.state = run.cancel ? "cancelled" : failed ? "failed" : "ok";
  run.finished_at = Date.now() / 1000;
  run.seconds = run.finished_at - run.started_at;
  const end = { ok: `✓ ${run.title} done`, cancelled: `■ ${run.title} cancelled` };
  out(run, [end[run.state] ?? `✗ ${run.title} failed`]);
  broadcast("run.finished", {
    run_id: run.run_id,
    action_id: run.action_id,
    state: run.state,
    ok: run.state === "ok",
    cancelled: run.state === "cancelled",
    seconds: run.seconds,
    steps: run.steps,
    error: run.error,
  });
}

function publicRun(run, withLines = false) {
  const { cancel, generation: _, lines, ...rest } = run;
  return withLines ? { ...rest, lines } : rest;
}

// ---- HTTP -------------------------------------------------------------------------------------------

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(text),
  });
  res.end(text);
}

const problem = (res, status, code, message, fix = "", detail = "", action = null) =>
  json(res, status, { error: { code, message, detail, fix, action } });

async function body(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 64 * 1024) throw Object.assign(new Error("too large"), { status: 413 });
    chunks.push(chunk);
  }
  const text = Buffer.concat(chunks).toString("utf8");
  return text ? JSON.parse(text) : {};
}

async function serveStatic(req, res, pathname) {
  const relative = pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
  const full = normalize(join(UI, relative));
  if (!full.startsWith(UI + sep) || !TYPES[extname(full)]) {
    return problem(res, 404, "not-found", "Not found");
  }
  try {
    const data = await readFile(full);
    res.writeHead(200, {
      "Content-Type": TYPES[extname(full)],
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    });
    res.end(data);
  } catch {
    problem(res, 404, "not-found", "Not found");
  }
}

function events(req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-store",
    Connection: "keep-alive",
  });
  res.write("retry: 3000\n\n");
  send(res, "hello", { api: 1, demo: world.demo, build: "mock", resync: false });
  send(res, "status", statusOf(world));
  clients.add(res);
  const ping = setInterval(() => res.write(": ping\n\n"), 15000);
  req.on("close", () => {
    clearInterval(ping);
    clients.delete(res);
  });
}

async function runAction(req, res, action) {
  const input = await body(req);
  const params = input.params ?? {};
  if (!action.enabled) {
    const code = action.safety === "refused" ? "refused" : "disabled";
    return problem(res, 403, code, action.reason || `${action.title} cannot run now.`);
  }
  for (const p of action.params) {
    const value = params[p.name];
    if (p.kind === "boolean") continue;
    const known = p.choices?.some((c) => c.value === value);
    if (p.choices && value !== undefined && value !== "" && !known) {
      return problem(res, 400, "bad-params", `${p.label} "${value}" is not one of the choices.`);
    }
    if (p.required !== false && (value === undefined || value === "")) {
      return problem(res, 400, "bad-params", `${action.title} needs a ${p.label.toLowerCase()}.`);
    }
  }
  const binding = { action: action.id, params: canonical(params) };
  if (action.needs_confirm && !redeem(input.confirm_token, binding)) {
    return problem(
      res,
      428,
      "confirm-required",
      `${action.title} needs a confirm.`,
      "Preview it again: the token is missing, used, expired or for other parameters.",
    );
  }
  if (action.kind === "open") {
    return json(res, 200, { opened: true, target: `/Users/me/compliancewatch/${action.command}` });
  }
  const busy = activeStep();
  if (busy && action.kind !== "read") {
    return problem(
      res,
      409,
      "busy",
      `${busy.title} is still running.`,
      "Wait for it to finish, or press Cancel.",
      "One task runs at a time.",
    );
  }
  return json(res, 202, { run_id: startRun(action, params).run_id });
}

function refreshKafka(res) {
  const since = (Date.now() - kafkaStartedAt) / 1000;
  if (since < 30) return json(res, 200, { started: false, next_in: Math.ceil(30 - since) });
  kafkaStartedAt = Date.now();
  lastKafka = { ...(lastKafka ?? kafkaOf(world)), reading: true };
  setTimeout(() => {
    lastKafka = { ...kafkaOf(world), next_in: 30, reading: false };
    broadcast("kafka", lastKafka);
  }, 400 / speed);
  return json(res, 200, { started: true, next_in: 30 });
}

const NO_KAFKA = { taken_at: null, groups: [], topics: [], error: "", next_in: 0, reading: false };

async function api(req, res, url) {
  const [head, id, sub] = url.pathname.split("/").filter(Boolean).slice(1);
  const method = req.method;
  const action = () => catalog().actions.find((a) => a.id === decodeURIComponent(id ?? ""));

  if (head === "events" && method === "GET") return events(req, res);
  if (head === "launch-code" && method === "POST") {
    const code = `l-${randomBytes(18).toString("base64url")}`;
    launches.set(code, Date.now() + 30000);
    return json(res, 200, { code, expires_in: 30 });
  }
  if (head === "status" && method === "GET") return json(res, 200, statusOf(world));
  if (head === "meta" && method === "GET") {
    return json(res, 200, { api: 1, demo: world.demo, build: "mock", repo: "/Users/me/cw" });
  }
  if (head === "actions" && method === "GET" && !id) return json(res, 200, catalog());
  if (head === "actions" && method === "POST" && sub === "preview") {
    const found = action();
    if (!found) return problem(res, 404, "not-found", "No such action.");
    const input = await body(req);
    return json(res, 200, previewOf(found, input.params ?? {}));
  }
  if (head === "actions" && method === "POST" && sub === "run") {
    const found = action();
    return found ? runAction(req, res, found) : problem(res, 404, "not-found", "No such action.");
  }
  if (head === "runs" && method === "GET" && !id) {
    const limit = Math.min(50, Math.max(1, Number(url.searchParams.get("limit") ?? 20)));
    return json(res, 200, { runs: runs.slice(0, limit).map((r) => publicRun(r)) });
  }
  if (head === "runs" && method === "GET" && id) {
    const run = runs.find((r) => r.run_id === id);
    return run
      ? json(res, 200, publicRun(run, true))
      : problem(res, 404, "not-found", "No such run.");
  }
  if (head === "runs" && method === "POST" && sub === "cancel") {
    const run = runs.find((r) => r.run_id === id);
    if (!run || run.state !== "running") {
      return problem(res, 409, "not-running", "That has already finished.");
    }
    run.cancel = true;
    return json(res, 200, { ok: true });
  }
  if (head === "features" && method === "GET") {
    // as the helper does: the first read happens in the background, and an event says so
    if (!featuresRead) {
      featuresRead = true;
      setTimeout(() => broadcast("features", {}), 300 / speed);
      return json(res, 200, { features: [], loading: true, reading: true });
    }
    return json(res, 200, { ...featuresOf(world), loading: false, reading: false });
  }
  if (head === "flags" && method === "GET") return json(res, 200, flagsOf());
  if (head === "processes" && method === "GET" && !id) return json(res, 200, processesOf(world));
  if (head === "processes" && method === "GET" && sub === "stop-preview") {
    const preview = stopPreviewOf(world, Number(id));
    const allowed = preview.options.some((o) => !o.refused && o.pids.length);
    return json(res, 200, {
      pid: Number(id),
      ...preview,
      warnings: preview.warnings ?? [],
      confirm_token: allowed ? issue({ action: `stop:${id}`, params: "" }) : null,
      expires_in: allowed ? 120 : 0,
    });
  }
  if (head === "processes" && method === "POST" && sub === "stop") {
    const input = await body(req);
    if (!redeem(input.confirm_token, { action: `stop:${id}`, params: "" })) {
      return problem(res, 428, "confirm-required", "Look at the stop again first.");
    }
    if (activeStep()) {
      return problem(res, 409, "busy", "Something else is running.", "Wait for it, or cancel it.");
    }
    world.sessions = world.sessions.filter((s) => String(s.pid) !== String(id));
    const run = startRun(
      {
        id: "process-stop",
        kind: "step",
        title: `Stop process ${id}`,
        steps: [`SIGTERM to pid ${id}`],
      },
      { mode: input.mode },
    );
    setTimeout(worldChanged, 500 / speed);
    return json(res, 202, { run_id: run.run_id });
  }
  if (head === "logs" && method === "GET" && !id) return json(res, 200, logSourcesOf());
  if (head === "logs" && method === "GET" && id) {
    const tail = Math.min(2000, Math.max(1, Number(url.searchParams.get("tail") ?? 500)));
    return json(res, 200, logOf(decodeURIComponent(id), tail));
  }
  if (head === "kafka" && method === "GET" && !id) return json(res, 200, lastKafka ?? NO_KAFKA);
  if (head === "kafka" && method === "POST" && id === "refresh") return refreshKafka(res);
  if (head === "docs" && method === "GET" && !id) return json(res, 200, DOCS);
  if (head === "docs" && method === "POST" && sub === "open") {
    const doc = DOCS.docs.find((d) => d.id === id);
    return doc
      ? json(res, 200, { opened: true, target: `/Users/me/cw/${doc.path}` })
      : problem(res, 404, "not-found", "No such document.");
  }
  if (head === "github" && method === "GET") return json(res, 200, githubOf(world));
  if (head === "heartbeat" && method === "POST") {
    return json(res, 200, { ok: true, idle_exit_in: 600 });
  }
  if (head === "prefs" && method === "GET") return json(res, 200, prefs);
  if (head === "prefs" && method === "PUT") {
    const input = await body(req);
    const unknown = Object.keys(input).filter((key) => !(key in prefs));
    if (unknown.length) {
      return problem(res, 400, "bad-params", `Unknown prefs: ${unknown.join(", ")}`);
    }
    prefs = { ...prefs, ...input };
    return json(res, 200, prefs);
  }
  return problem(res, 404, "not-found", "No such route.");
}

async function control(req, res) {
  const input = await body(req);
  if (input.reset) {
    world = baseWorld();
    runs.length = 0;
    failNext = null;
    lastKafka = null;
    kafkaStartedAt = 0;
    featuresRead = false;
    generation += 1;
  }
  if (input.world) {
    const product = { ...world.product, ...(input.world.product ?? {}) };
    world = { ...world, ...input.world, product };
    if (input.world.sessions === "agent") world.sessions = [AGENT_SESSION];
    if (input.world.sessions === "terminal")
      world.sessions = [{ ...AGENT_SESSION, kind: "terminal" }];
    if (input.world.sessions === "none") world.sessions = [];
  }
  if (input.prefs) prefs = { ...prefs, ...input.prefs };
  if ("failNext" in input) failNext = input.failNext;
  if (input.expireTokens) tokens.clear();
  if (input.speed) speed = Number(input.speed);
  worldChanged();
  json(res, 200, { ok: true, world, prefs });
}

const launches = new Map();
const WHO = { agent: "Claude's build agent", terminal: "A terminal" };

const server = createServer(async (req, res) => {
  try {
    if (req.headers.host !== `127.0.0.1:${port}`) {
      return problem(res, 403, "bad-host", "Wrong Host header.");
    }
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    const isApi = url.pathname.startsWith("/api/") || url.pathname.startsWith("/__mock/");
    if (isApi && url.pathname === "/api/launch") {
      // the one route without the token: a page of this helper swaps its launch code, once
      if (req.method !== "POST") return problem(res, 405, "method-not-allowed", "POST only.");
      if (req.headers.origin !== `http://127.0.0.1:${port}`) {
        return problem(res, 403, "bad-origin", "Foreign origin.");
      }
      const input = await body(req);
      const expires = launches.get(input.code);
      launches.delete(input.code);
      if (!expires || expires < Date.now()) {
        return problem(
          res,
          401,
          "launch-expired",
          "This window's link has been used or has expired.",
        );
      }
      return json(res, 200, { token: TOKEN });
    }
    if (isApi) {
      if (req.headers.origin && req.headers.origin !== `http://127.0.0.1:${port}`) {
        return problem(res, 403, "bad-origin", "Foreign origin.");
      }
      if (req.headers["x-panel-token"] !== TOKEN) {
        return problem(res, 401, "unauthorized", "Missing or wrong token.");
      }
      if (url.pathname === "/__mock/state" && req.method === "POST") return await control(req, res);
      return await api(req, res, url);
    }
    if (req.method !== "GET") {
      return problem(res, 405, "method-not-allowed", "Method not allowed.");
    }
    return await serveStatic(req, res, url.pathname);
  } catch (error) {
    if (error.status === 413) return problem(res, 413, "too-large", "Request too large.");
    if (error instanceof SyntaxError) return problem(res, 400, "bad-json", "The body is not JSON.");
    console.error(error);
    return problem(res, 500, "internal", "The mock failed.", "", String(error));
  }
});

server.listen(Number(flag("port", 0)) || 0, "127.0.0.1", () => {
  port = server.address().port;
  process.stdout.write(`${JSON.stringify({ port, token: TOKEN })}\n`);
});

const stop = () => {
  for (const res of clients) res.end();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 500).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
