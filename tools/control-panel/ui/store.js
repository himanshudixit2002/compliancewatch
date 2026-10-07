// The window's state and who listens to it. Views subscribe to topics ("status", "actions",
// "runs", "run:<id>", "lines:<id>", "connection", ...) and patch their own DOM when told.

import {
  normalizeActions,
  normalizeLine,
  normalizeRun,
  normalizeStatus,
  normalizeStep,
  partsOf,
} from "./model.js";

const MAX_LINES = 4000;

const listeners = new Map();

export const state = {
  connection: "connecting",
  hello: { demo: false, build: "" },
  status: null,
  statusError: null,
  parts: partsOf(null, null),
  actions: [],
  actionsById: new Map(),
  groups: [],
  actionsLoaded: false,
  runs: new Map(),
  runOrder: [],
  prefs: {},
  cache: {},
};

export function on(topic, fn) {
  if (!listeners.has(topic)) listeners.set(topic, new Set());
  listeners.get(topic).add(fn);
  return () => listeners.get(topic)?.delete(fn);
}

export function emit(topic, payload) {
  for (const fn of [...(listeners.get(topic) ?? [])]) {
    try {
      fn(payload);
    } catch (error) {
      console.error(`listener of ${topic} failed`, error);
    }
  }
}

export function setConnection(value) {
  if (state.connection === value) return;
  state.connection = value;
  emit("connection", value);
}

export function setHello(data) {
  state.hello = { demo: Boolean(data?.demo), build: String(data?.build ?? "") };
  emit("hello", state.hello);
}

export function setStatus(raw) {
  state.status = normalizeStatus(raw);
  state.statusError = null;
  if (state.status.demo) state.hello = { ...state.hello, demo: true };
  refreshParts();
  emit("status", state.status);
}

export function setStatusError(error) {
  state.statusError = error;
  emit("status", state.status);
}

export function setActions(raw) {
  const { actions, groups } = normalizeActions(raw);
  state.actions = actions;
  state.groups = groups;
  state.actionsById = new Map(actions.map((a) => [a.id, a]));
  state.actionsLoaded = true;
  emit("actions", actions);
}

export function action(id) {
  return state.actionsById.get(id) ?? null;
}

/** The step running now (one at a time); reads may run beside it. */
export function activeRun() {
  for (const id of state.runOrder) {
    const run = state.runs.get(id);
    if (run?.state === "running" && (run.kind || action(run.actionId)?.kind) !== "read") return run;
  }
  return null;
}

/** The latest run of an action, running or finished. */
export function latestRunOf(actionId) {
  for (const id of state.runOrder) {
    const run = state.runs.get(id);
    if (run?.actionId === actionId) return run;
  }
  return null;
}

function refreshParts() {
  state.parts = partsOf(state.status, activeRun());
  emit("parts", state.parts);
}

function ensureRun(id, seed = {}) {
  let run = state.runs.get(id);
  if (!run) {
    run = normalizeRun({ run_id: id, state: "running", ...seed });
    run.lines = [];
    run.dropped = 0;
    state.runs.set(id, run);
    state.runOrder.unshift(id);
  }
  return run;
}

function touch(run) {
  emit(`run:${run.id}`, run);
  emit("runs", run);
  refreshParts();
}

/** Recent runs from GET /api/runs, merged with what the stream already told. */
export function mergeRuns(raw) {
  const items = (raw?.runs ?? raw ?? []).map(normalizeRun);
  for (const item of items.reverse()) {
    const known = state.runs.get(item.id);
    if (known) {
      if (known.state === "running" && item.state !== "running") Object.assign(known, item);
      continue;
    }
    item.lines = item.lines ?? [];
    item.dropped = 0;
    state.runs.set(item.id, item);
    state.runOrder.unshift(item.id);
  }
  state.runOrder.sort(
    (a, b) => (state.runs.get(b)?.startedAt ?? 0) - (state.runs.get(a)?.startedAt ?? 0),
  );
  emit("runs", null);
  refreshParts();
}

export function runStarted(data) {
  const run = ensureRun(String(data.run_id), data);
  Object.assign(run, {
    actionId: String(data.action_id ?? run.actionId),
    kind: String(data.kind ?? run.kind ?? ""),
    title: normalizeRun(data).title || run.title,
    state: "running",
    startedAt: data.started_at ?? run.startedAt ?? Date.now() / 1000,
    steps: (data.steps ?? []).map(normalizeStep),
    cleanup: (data.cleanup ?? run.cleanup ?? []).map(String),
    error: null,
  });
  touch(run);
  emit("run.started", run);
}

export function runStep(data) {
  const run = ensureRun(String(data.run_id));
  const index = Number(data.index);
  while (run.steps.length <= index) run.steps.push(normalizeStep({ label: "", state: "pending" }));
  run.steps[index] = normalizeStep({
    label: data.label ?? run.steps[index].label,
    state: data.state,
    seconds: data.seconds,
  });
  touch(run);
}

export function runOutput(data) {
  const run = ensureRun(String(data.run_id));
  const lines = (data.lines ?? (data.text !== undefined ? [data] : [])).map(normalizeLine);
  run.lines.push(...lines);
  if (run.lines.length > MAX_LINES) {
    const extra = run.lines.length - MAX_LINES;
    run.lines.splice(0, extra);
    run.dropped += extra;
  }
  emit(`lines:${run.id}`, lines);
}

export function runFinished(data) {
  const run = ensureRun(String(data.run_id));
  const finished = normalizeRun({ ...data, state: data.state });
  run.state = data.state ?? (data.cancelled ? "cancelled" : data.ok === false ? "failed" : "ok");
  run.seconds = finished.seconds ?? run.seconds;
  run.finishedAt = data.finished_at ?? Date.now() / 1000;
  if (finished.steps.length) run.steps = finished.steps;
  run.error = finished.error;
  touch(run);
  emit("run.finished", run);
}

/** Lines a run printed before this window saw it (GET /api/runs/{id}). */
export function fillLines(id, raw) {
  const run = state.runs.get(id);
  if (!run) return;
  const detail = normalizeRun(raw);
  if (detail.lines.length >= run.lines.length) run.lines = detail.lines;
  if (detail.steps.length && !run.steps.length) run.steps = detail.steps;
  run.linesLoaded = true;
  emit(`lines:${id}`, null);
}

export function setCache(key, value) {
  state.cache[key] = { value, at: Date.now() };
  emit(`cache:${key}`, value);
}

export function cached(key) {
  return state.cache[key]?.value;
}
