// Running an action: availability, the parameter and confirm dialogs, the request, and what the
// window shows while it runs and after it ends (the action card, the run panel, toasts).

import { api, ApiError } from "./api.js";
import { add, cx, formatAgo, formatDuration, h, put, stepLabel, uid } from "./dom.js";
import { icon } from "./icons.js";
import { buttonLabel, checkoutWarnings, explainFailure, runProgress, SAFETY } from "./model.js";
import * as store from "./store.js";
import {
  announce,
  banner,
  button,
  copyButton,
  disclosure,
  openDialog,
  outputView,
  progressBar,
  safetyBadge,
  spinner,
  toast,
} from "./ui.js";

const ICONS = [
  [/^start-everything$/, "play"],
  [/^stop-everything$/, "power"],
  [/^docker/, "container"],
  [/^databases|^migrat|^data-quality|^seed|^psql/, "database"],
  [/^ui-/, "server"],
  [/^web-/, "globe"],
  [/^product-check|^gate|^gates|check$/, "checks"],
  [/^product-e2e/, "globe"],
  [/^product|^mvp/, "package"],
  [/^load-demo|^demo/, "sparkles"],
  [/^backup/, "download"],
  [/^restore/, "upload"],
  [/^reset/, "rotate"],
  [/^worker/, "cpu"],
  [/^relay/, "wave"],
  [/logs|^dev-ps/, "logs"],
  [/^crawl/, "pipeline"],
  [/^flags|^open-env/, "flag"],
  [/^doctor/, "help"],
  [/^dev-observability/, "gauge"],
  [/^dev-llm/, "sparkles"],
  [/^dev-flags/, "flag"],
];

export function actionIcon(action) {
  const id = action?.id ?? "";
  return (
    ICONS.find(([pattern]) => pattern.test(id))?.[1] ??
    (action?.kind === "open" ? "external" : "terminal")
  );
}

// ---- may it run now? ----------------------------------------------------------------------------

export function availability(action) {
  if (!action) return { enabled: false, reason: "This version of the app does not have it." };
  if (store.state.connection === "unauthorized") {
    return { enabled: false, reason: "This window lost its key. Reopen the app." };
  }
  if (store.state.connection === "offline") {
    return { enabled: false, reason: "The app's helper is not answering." };
  }
  if (!action.enabled)
    return { enabled: false, reason: action.reason || "Not available right now." };
  const active = store.activeRun();
  if (active && action.kind === "step" && active.actionId !== action.id) {
    return {
      enabled: false,
      busy: true,
      reason: `Waits for "${active.title}" to finish. Cancel it to run this now.`,
    };
  }
  return { enabled: true, reason: "" };
}

function defaultParams(action, given = {}) {
  const params = {};
  for (const p of action.params) {
    params[p.name] = given[p.name] ?? p.default;
  }
  return params;
}

/** Whether the window asks before running: always, for every action that is not safe or that
 * the helper says needs a confirm (a model call among them), warnings or none. A risky action is
 * never confirmed for the person. */
function shouldAsk(action) {
  if (action.kind === "open") return false;
  return Boolean(action.needsConfirm) || action.safety !== "safe";
}

function paramField(p, value, onChange) {
  const id = uid(`param-${p.name}`);
  if (p.type === "boolean") {
    const box = h("input", {
      attrs: { type: "checkbox", id },
      props: { checked: Boolean(value) },
      on: { change: (e) => onChange(e.target.checked) },
    });
    return h(
      "label",
      { class: "check-field", attrs: { for: id } },
      box,
      h("span", { text: p.label }),
    );
  }
  if (p.choices.length) {
    const select = h(
      "select",
      { class: "select", attrs: { id }, on: { change: (e) => onChange(e.target.value) } },
      p.choices.map((c) =>
        h("option", {
          text: c.note ? `${c.label} · ${c.note}` : c.label,
          props: { value: c.value, selected: c.value === String(value) },
        }),
      ),
    );
    return h(
      "div",
      { class: "field" },
      h("label", { class: "field-label", text: p.label, attrs: { for: id } }),
      select,
    );
  }
  const input = h("input", {
    class: "input",
    attrs: { id, type: "text", autocomplete: "off" },
    props: { value: value ?? "" },
    on: { input: (e) => onChange(e.target.value) },
  });
  return h(
    "div",
    { class: "field" },
    h("label", { class: "field-label", text: p.label, attrs: { for: id } }),
    input,
  );
}

/** The confirm a risky action asks, in plain words, with the checkout's warnings. */
const WARNING_TONES = {
  sessions: "danger",
  "not-main": "warning",
  dirty: "warning",
  "docker-down": "warning",
  "product-down": "warning",
};

/** A warning from a preview ({code, tone, title, message, items}) or from the window itself. */
function normalizeWarning(w) {
  if (typeof w === "string") return { tone: "warning", title: w, body: "", items: [] };
  const titled = Boolean(w.title && w.message);
  const body = String(titled ? w.message : (w.body ?? ""));
  let items = Array.isArray(w.items) ? w.items.map(String) : [];
  // one item the sentence already says ("...: make check (pid 61000, 3m 12s)") is not repeated
  if (items.length === 1 && body.includes(items[0].split(": ").slice(1).join(": ") || items[0]))
    items = [];
  return {
    tone: ["warning", "danger", "info"].includes(w.tone)
      ? w.tone
      : (WARNING_TONES[w.code] ?? "info"),
    title: String(titled ? w.title : (w.message ?? w.title ?? "")),
    body,
    items,
  };
}

/** What a preview says, in the dialog's terms (API.md, section 4). */
function readPreview(preview) {
  const c = preview?.confirm;
  const token = preview?.confirm_token ? String(preview.confirm_token) : null;
  if (!c || typeof c !== "object") return { token, warnings: [] };
  return {
    token,
    title: String(c.title ?? ""),
    text: String(c.text ?? ""),
    whatHappens: Array.isArray(c.what_happens) ? c.what_happens.map(String) : [],
    warnings: Array.isArray(c.warnings) ? c.warnings.map(normalizeWarning) : [],
    button: String(c.button ?? ""),
    reaches: Array.isArray(preview.reaches ?? c.reaches) ? (preview.reaches ?? c.reaches) : [],
    command: String(c.details || preview.command || ""),
  };
}

/**
 * The question a risky action asks: what happens, in plain words, what it reaches, its safety,
 * the preview's warnings, its options (a changed option previews again, since a confirm token
 * is bound to its exact parameters), the "I understand" tick for a deletion, and the commands
 * behind "Show technical details". Resolves with { params, token }, or null.
 */
async function confirmRun(action, params, info) {
  const meta = SAFETY[action.safety] ?? SAFETY.safe;
  const danger = action.safety === "destructive" || action.safety === "stops-things";
  const values = { ...params };
  let token = info?.token ?? null;
  let acknowledged = action.safety !== "destructive";
  let pending = false;
  let confirmButton = null;
  const sync = () => {
    if (!confirmButton) return;
    confirmButton.disabled = !acknowledged || pending;
    confirmButton.toggleAttribute("aria-busy", pending);
  };
  const whatList = h("ul", { class: "confirm-list" });
  const optionNote = h("p", { class: "confirm-note", attrs: { role: "status" } });
  const showWhat = (current) => {
    const lines = current?.whatHappens?.length
      ? current.whatHappens
      : action.whatHappens.length
        ? action.whatHappens
        : [action.summary];
    put(
      whatList,
      lines.map((line) => h("li", { text: line })),
    );
  };
  showWhat(info);
  const booleanParams = action.params.filter((p) => p.type === "boolean");
  const repreview = async () => {
    if (!action.needsConfirm) return;
    pending = true;
    sync();
    optionNote.textContent = "Checking again…";
    try {
      const next = readPreview(await api.preview(action.id, values));
      token = next.token;
      showWhat(next);
      optionNote.textContent = "";
    } catch (error) {
      token = null;
      optionNote.textContent =
        error.title || "The helper did not answer; close this and try again.";
    } finally {
      pending = false;
      sync();
    }
  };
  const reaches = info?.reaches ?? [];
  const result = await openDialog({
    title: info?.title || `${action.title}?`,
    tone: action.safety === "destructive" ? "danger" : danger ? "warning" : "info",
    iconName: meta.icon,
    size: "md",
    build: () => [
      h("p", { class: "dialog-lead", text: info?.text || action.summary }),
      h(
        "div",
        { class: "confirm-what" },
        h("p", { class: "confirm-label", text: "What happens" }),
        whatList,
      ),
      reaches.length
        ? h(
            "div",
            { class: "confirm-what" },
            h("p", { class: "confirm-label", text: "These processes get a request to stop" }),
            h(
              "ul",
              { class: "pid-list" },
              reaches.map((p) =>
                h(
                  "li",
                  {},
                  h("code", { text: String(p.pid ?? p) }),
                  h("span", { class: "cmd", text: String(p.command ?? "") }),
                ),
              ),
            ),
          )
        : null,
      h(
        "p",
        { class: "confirm-safety" },
        safetyBadge(action.safety),
        h("span", { text: meta.plain }),
      ),
      ...(info?.warnings ?? []).map((w) =>
        banner({ tone: w.tone, title: w.title, body: w.body, items: w.items, role: "note" }),
      ),
      booleanParams.length
        ? h(
            "div",
            { class: "confirm-options" },
            booleanParams.map((p) =>
              paramField(p, values[p.name], (v) => {
                values[p.name] = v;
                repreview();
              }),
            ),
            optionNote,
          )
        : null,
      action.safety === "destructive"
        ? h(
            "label",
            { class: "check-field confirm-ack" },
            h("input", {
              attrs: { type: "checkbox" },
              on: {
                change: (e) => {
                  acknowledged = e.target.checked;
                  sync();
                },
              },
            }),
            h("span", { text: "I understand that this deletes local data." }),
          )
        : null,
      info?.command || action.command
        ? disclosure({
            label: "Show technical details",
            openLabel: "Hide technical details",
            content: () => h("pre", { class: "code-block", text: info?.command || action.command }),
          }).el
        : null,
    ],
    actions: [
      { label: "Cancel", value: null, autofocus: danger, key: "cancel" },
      {
        label: info?.button || action.button || buttonLabel(action),
        value: () => ({ params: { ...values }, token }),
        variant: danger ? "danger" : "primary",
        autofocus: !danger,
        key: "confirm",
        disabled: action.safety === "destructive",
        ref: (el) => {
          confirmButton = el;
        },
      },
    ],
  });
  return result;
}

async function askParams(action, params) {
  const values = { ...params };
  const result = await openDialog({
    title: action.title,
    iconName: actionIcon(action),
    build: () => [
      action.summary ? h("p", { class: "dialog-lead", text: action.summary }) : null,
      h(
        "div",
        { class: "param-fields" },
        action.params.map((p) => paramField(p, values[p.name], (v) => (values[p.name] = v))),
      ),
    ],
    actions: [
      { label: "Cancel", value: null, key: "cancel" },
      {
        label: action.button || buttonLabel(action),
        value: () => values,
        variant: "primary",
        autofocus: true,
        key: "confirm",
      },
    ],
  });
  return result;
}

const toasted = new Set();
let openActivity = () => {};
export function onOpenActivity(fn) {
  openActivity = fn;
}

/** Opens the Activity sheet, at one run when an id is given. */
export function showActivity(runId) {
  openActivity(runId);
}

// ---- one question at a time ----------------------------------------------------------------------

let asking = "";

/**
 * Runs fn unless another press is still on its way from its click to its start (a preview being
 * read, a question open, the start request in flight): a second press then does nothing, so two
 * quick clicks never open two questions or start a thing twice.
 */
export async function oneQuestion(key, fn) {
  if (asking) return null;
  asking = key;
  try {
    return await fn();
  } finally {
    asking = "";
  }
}

/**
 * Runs an action the way every button does: checks it may run, asks for missing parameters,
 * previews anything that is not safe (API.md: the preview gives the warnings and the token the
 * run must carry), asks when it stops or deletes something or the preview warns, then starts
 * it. Resolves with the run id, or null when it did not start (or another press was on its way).
 */
export function runAction(id, options = {}) {
  return oneQuestion(id, () => startAction(id, options));
}

async function startAction(id, { params = {}, ask = false, retried = false } = {}) {
  const action = store.action(id);
  const can = availability(action);
  if (!can.enabled) {
    toast({
      level: "warning",
      title: action ? `${action.title} cannot run now` : "Not available",
      body: can.reason,
      actions: can.busy ? [{ label: "Show what is running", onClick: () => openActivity() }] : [],
    });
    return null;
  }
  if (action.kind === "open" && action.url) {
    openUrl(action.url);
    return null;
  }
  let values = defaultParams(action, params);
  const missing = action.params.some((p) => p.required && p.type !== "boolean" && !values[p.name]);
  if ((ask || missing) && action.params.some((p) => p.type !== "boolean")) {
    values = await askParams(action, values);
    if (!values) return null;
  }
  let info = null;
  if (action.needsConfirm && action.kind !== "open") {
    try {
      info = readPreview(await api.preview(action.id, values));
    } catch (error) {
      if (error.status !== 404) {
        showRequestError(error, action);
        return null;
      }
      // a helper without previews: the window's own warnings, and no token
      info = { token: null, warnings: checkoutWarnings(store.state.status) };
    }
  }
  let token = info?.token ?? null;
  if (shouldAsk(action)) {
    const answer = await confirmRun(action, values, info);
    if (!answer) return null;
    values = answer.params;
    token = answer.token;
  }
  try {
    const answer = await api.run(action.id, values, token);
    const runId = String(answer.run_id ?? answer.id ?? "");
    if (runId && !store.state.runs.has(runId) && action.kind !== "open") {
      store.runStarted({
        run_id: runId,
        action_id: action.id,
        title: action.title,
        kind: action.kind,
        steps: action.steps,
        started_at: Date.now() / 1000,
        params: values,
      });
    }
    if (action.kind === "open") {
      const target = String(answer.target ?? "")
        .split("/")
        .filter(Boolean)
        .at(-1);
      toast({ level: "success", title: target ? `Opened ${target}` : `${action.title}: done` });
    } else {
      announce(`${action.title} started`);
    }
    return runId || null;
  } catch (error) {
    if (error.code === "confirm-required" && !retried) {
      toast({
        level: "info",
        title: "That question had expired",
        body: "What it reaches may have changed, so here it is again.",
      });
      return startAction(id, { params: values, retried: true });
    }
    showRequestError(error, action);
    return null;
  }
}

export function showRequestError(error, action) {
  const e = error instanceof ApiError ? error : new ApiError({ detail: String(error) });
  if (e.code === "not-running") {
    toast({ level: "info", title: "It has already finished", body: e.title || "" });
    return;
  }
  if (e.code === "busy" || e.status === 409) {
    toast({
      level: "warning",
      title: e.title || "Something else is running",
      body: e.fix || e.detail || "Wait for it to finish, or cancel it, then try again.",
      actions: [{ label: "Show what is running", onClick: () => openActivity() }],
    });
    return;
  }
  if (e.code === "offline") {
    toast({
      level: "error",
      title: "The app's helper is not answering",
      body: "It may have stopped. Wait a few seconds; if this keeps happening, quit the app and open it again.",
    });
    return;
  }
  if (e.status === 401 || (e.status === 403 && e.code === "unauthorized")) {
    store.setConnection("unauthorized");
    return;
  }
  const fixAction = e.action ? store.action(e.action) : null;
  toast({
    level: "error",
    title: e.title || (action ? `${action.title} did not start` : "That did not work"),
    body: e.fix || e.detail || "The helper refused it.",
    actions: fixAction
      ? [{ label: fixAction.title, variant: "primary", onClick: () => runAction(fixAction.id) }]
      : [],
  });
}

export function cancelRun(run) {
  return oneQuestion(`cancel:${run.id}`, () => askCancel(run));
}

async function askCancel(run) {
  const choice = await openDialog({
    title: `Cancel "${run.title}"?`,
    tone: "warning",
    iconName: "stop",
    build: () => [
      h("p", {
        text: "The step running now is stopped, with everything it started, and the steps after it do not run. What already finished stays as it is.",
      }),
    ],
    actions: [
      { label: "Keep it running", value: null, autofocus: true, key: "keep" },
      { label: "Cancel it", value: true, variant: "danger", key: "cancel-run" },
    ],
  });
  if (!choice) return;
  try {
    await api.cancel(run.id);
    announce(`Cancelling ${run.title}`);
  } catch (error) {
    showRequestError(error);
  }
}

/** Opens a page in the default browser (the app shell hands target=_blank links to it). */
export function openUrl(url) {
  const a = h("a", { attrs: { href: url, target: "_blank", rel: "noopener noreferrer" } });
  add(document.body, a);
  a.click();
  a.remove();
}

/** The URLs the Guide and Home open: the web app, the product and its sign-in page. */
export function targetUrl(kind) {
  const status = store.state.status;
  const parts = store.state.parts;
  if (kind === "web")
    return { url: parts.web.url || "http://localhost:3000", up: parts.web.state === "running" };
  const base = parts.product.url || "http://127.0.0.1:3400";
  const up = status?.product.web.up === true;
  if (kind === "signin") return { url: `${base}/sign-in`, up };
  if (kind === "admin") return { url: `${base}/admin`, up };
  return { url: base, up };
}

// ---- after a run ------------------------------------------------------------------------------

const FOLLOW_UPS = {
  "start-everything": [{ open: "web", label: "Open the app" }],
  "load-demo-data": [{ open: "web", label: "Open the app" }],
  "product-start": [
    { action: "product-seed", label: "Fill it with sample data" },
    { open: "product", label: "Open the product" },
  ],
  "product-seed": [
    { action: "product-check", label: "Check it works" },
    { open: "signin", label: "Open the sign-in page" },
  ],
  "web-start": [{ open: "web", label: "Open the app" }],
};

function followUps(run) {
  return (FOLLOW_UPS[run.actionId] ?? [])
    .filter((f) => !f.action || store.action(f.action))
    .map((f) => ({
      label: f.label,
      variant: "primary",
      onClick: () => (f.open ? openUrl(targetUrl(f.open).url) : runAction(f.action)),
    }));
}

/** The toast a finished run gets (once, whoever reports it first). */
export function notifyRunFinished(run) {
  if (toasted.has(run.id)) return;
  toasted.add(run.id);
  const action = store.action(run.actionId);
  const took = run.seconds ? ` in ${formatDuration(run.seconds)}` : "";
  if (action?.kind === "read" && run.state === "ok") {
    toast({
      level: "success",
      title: `${run.title}: ready`,
      body: "Its output is in Activity.",
      actions: [{ label: "Show the output", onClick: () => openActivity(run.id) }],
    });
    return;
  }
  if (run.state === "ok") {
    toast({
      level: "success",
      title: `${run.title}: done`,
      body:
        run.actionId === "stop-everything"
          ? `Stopped${took}. Your data is kept.`
          : `Finished${took}.`,
      actions: followUps(run),
    });
    return;
  }
  if (run.state === "cancelled") {
    toast({
      level: "info",
      title: `${run.title}: cancelled`,
      body: "The running step was stopped.",
    });
    return;
  }
  const why = explainFailure(run, run.lines);
  const fix = why?.action ? store.action(why.action) : null;
  toast({
    level: "error",
    title: why?.title?.startsWith(run.title)
      ? why.title
      : `${run.title} failed: ${why?.title ?? "see what happened"}`,
    body: why?.fix ?? "",
    actions: [
      ...(fix ? [{ label: fix.title, variant: "primary", onClick: () => runAction(fix.id) }] : []),
      ...(why?.go ? [{ label: "Go there", onClick: () => (window.location.hash = why.go) }] : []),
      { label: "Show what happened", onClick: () => openActivity(run.id) },
    ],
  });
}

// ---- a clock for everything that shows elapsed time -------------------------------------------

const tickers = new Set();
window.setInterval(() => {
  for (const fn of tickers) fn();
}, 1000);

function elapsedOf(run) {
  if (!run.startedAt) return null;
  const end = run.state === "running" ? Date.now() / 1000 : (run.finishedAt ?? Date.now() / 1000);
  return run.seconds && run.state !== "running" ? run.seconds : end - run.startedAt;
}

// ---- the run panel ------------------------------------------------------------------------------

/**
 * What a run is doing: its progress and current step in words, Cancel, the plain reason and
 * fix when it failed, and its output behind a toggle.
 */
export function runPanel(run, { showSteps = false, openOutput = false } = {}) {
  const progress = progressBar({ label: `${run.title} progress` });
  const stateIcon = h("span", { class: "run-state-icon" });
  const headline = h("p", { class: "run-headline" });
  const time = h("span", { class: "run-time" });
  const cancel = button({
    label: "Cancel",
    icon: "stop",
    size: "sm",
    variant: "danger-ghost",
    onClick: () => cancelRun(store.state.runs.get(run.id) ?? run),
  });
  const stepsList = h("ol", { class: "run-steps", attrs: { hidden: !showSteps } });
  const failure = h("div", { class: "run-failure", attrs: { hidden: true } });
  const output = outputView({ label: `Output of ${run.title}` });
  let unsubscribeLines = null;
  const outputRegion = h(
    "div",
    { class: "run-output", attrs: { hidden: true } },
    h(
      "div",
      { class: "run-output-bar" },
      copyButton(() => output.text(), { label: "Copy output" }),
    ),
    output.el,
  );
  const outputId = uid("run-output");
  outputRegion.id = outputId;
  const outputToggle = h(
    "button",
    {
      class: "disclosure",
      attrs: { type: "button", "aria-expanded": "false", "aria-controls": outputId },
      on: { click: () => setOutput(outputRegion.hidden) },
    },
    icon("chevron-right", { size: 14 }),
    h("span", { class: "label", text: "Show the output" }),
  );

  function setOutput(open) {
    const current = store.state.runs.get(run.id) ?? run;
    outputRegion.hidden = !open;
    outputToggle.setAttribute("aria-expanded", String(open));
    outputToggle.querySelector(".label").textContent = open
      ? "Hide the output"
      : current.state === "running"
        ? "Show the live output"
        : "Show the output";
    if (open && !unsubscribeLines) {
      output.reset(current.lines, current.dropped ?? 0);
      unsubscribeLines = store.on(`lines:${run.id}`, (lines) => {
        if (lines === null) output.reset(store.state.runs.get(run.id)?.lines ?? []);
        else output.append(lines);
      });
      if (current.state !== "running" && !current.linesLoaded && !current.lines.length) {
        api.runDetail(run.id).then(
          (detail) => store.fillLines(run.id, detail),
          () => {},
        );
      }
    }
  }

  const el = h(
    "div",
    { class: "run-panel", attrs: { "aria-live": "polite" } },
    h("div", { class: "run-head" }, stateIcon, headline, time, cancel),
    progress.el,
    stepsList,
    failure,
    h("div", { class: "run-tools" }, outputToggle),
    outputRegion,
  );

  let lastState = "";
  function update(next = store.state.runs.get(run.id) ?? run) {
    el.dataset.state = next.state;
    const p = runProgress(next);
    const running = next.state === "running";
    cancel.hidden = !running;
    if (running) {
      progress.set(p.value);
      headline.textContent = p.total
        ? `Step ${p.index + 1} of ${p.total}: ${p.label}`
        : `${next.title} is running`;
    } else {
      progress.set(1);
      if (next.state === "ok")
        headline.textContent = `Done${next.seconds ? ` in ${formatDuration(next.seconds)}` : ""}`;
      else if (next.state === "cancelled") headline.textContent = "Cancelled";
      else headline.textContent = explainFailure(next, next.lines)?.title ?? "Failed";
    }
    if (lastState !== next.state) {
      put(
        stateIcon,
        running
          ? spinner()
          : icon(
              next.state === "ok"
                ? "check-circle"
                : next.state === "cancelled"
                  ? "minus-circle"
                  : "x-circle",
              {
                size: 18,
              },
            ),
      );
      outputToggle.querySelector(".label").textContent = !outputRegion.hidden
        ? "Hide the output"
        : running
          ? "Show the live output"
          : "Show the output";
      lastState = next.state;
    }
    renderSteps(next);
    renderFailure(next);
    tick();
  }

  function renderSteps(next) {
    if (stepsList.hidden) return;
    put(
      stepsList,
      ...next.steps.map((step) =>
        h(
          "li",
          { class: "run-step", data: { state: step.state } },
          h("span", { class: "run-step-icon" }, stepIcon(step.state)),
          h("span", { class: "run-step-label", text: stepLabel(step.label) }),
          h("span", {
            class: "run-step-time",
            text:
              step.state === "timeout"
                ? `timed out${step.seconds ? ` after ${formatDuration(step.seconds)}` : ""}`
                : step.seconds
                  ? formatDuration(step.seconds)
                  : stepWord(step.state),
          }),
        ),
      ),
    );
  }

  function renderFailure(next) {
    if (next.state !== "failed" && next.state !== "cancelled") {
      failure.hidden = true;
      return;
    }
    const why = explainFailure(next, next.lines);
    if (!why || next.state === "cancelled") {
      failure.hidden = true;
      return;
    }
    const fix = why.action ? store.action(why.action) : null;
    const again = store.action(next.actionId);
    failure.hidden = false;
    put(
      failure,
      h("p", { class: "run-fix", text: why.fix }),
      h(
        "div",
        { class: "run-fix-actions" },
        fix
          ? button({
              label: fix.title,
              icon: actionIcon(fix),
              variant: "primary",
              size: "sm",
              onClick: () => runAction(fix.id),
            })
          : null,
        why.go
          ? button({
              label: "Go there",
              icon: "arrow-right",
              size: "sm",
              onClick: () => (window.location.hash = why.go),
            })
          : null,
        again
          ? button({
              label: "Try again",
              icon: "refresh",
              size: "sm",
              onClick: () => runAction(again.id, { params: next.params ?? {} }),
            })
          : null,
      ),
      why.detail
        ? disclosure({
            label: "Show technical details",
            openLabel: "Hide technical details",
            content: () => h("pre", { class: "code-block", text: why.detail }),
          }).el
        : null,
    );
  }

  function tick() {
    const current = store.state.runs.get(run.id) ?? run;
    const seconds = elapsedOf(current);
    time.textContent = seconds === null ? "" : formatDuration(seconds);
  }

  const offRun = store.on(`run:${run.id}`, (next) => update(next));
  tickers.add(tick);
  update(run);
  if (openOutput) setOutput(true);

  return {
    el,
    update,
    setOutput,
    destroy() {
      offRun();
      unsubscribeLines?.();
      tickers.delete(tick);
    },
  };
}

function stepIcon(state) {
  const name = {
    ok: "check-circle",
    failed: "x-circle",
    timeout: "clock",
    cancelled: "minus-circle",
    skipped: "minus-circle",
    running: "",
  }[state];
  if (state === "running") return spinner();
  return icon(name || "dot", { size: 16 });
}

function stepWord(state) {
  return (
    {
      pending: "",
      running: "running",
      skipped: "skipped",
      cancelled: "cancelled",
      timeout: "timed out",
    }[state] ?? ""
  );
}

// ---- the action card ---------------------------------------------------------------------------

/**
 * One action as a card: title, plain line, safety, duration, what happens, one main button.
 * While it runs the card shows its run panel; after a failure, the plain reason and the fix.
 */
export function actionCard(actionId, { variant = "card", showIcon = true } = {}) {
  let panel = null;
  let panelRunId = "";
  let params = {};
  const root = h("article", {
    class: cx("action-card", variant === "row" ? "is-row" : "card"),
    attrs: { id: `action-${actionId}` },
  });

  function render() {
    const action = store.action(actionId);
    put(root);
    if (!action) {
      root.dataset.state = "missing";
      add(
        root,
        h(
          "div",
          { class: "ac-head" },
          h("h3", { class: "ac-title", text: actionId }),
          h("p", {
            class: "ac-summary",
            text: "This version of the app does not have this action.",
          }),
        ),
      );
      return;
    }
    params = { ...defaultParamsFor(action), ...params };
    const titleId = uid("ac-title");
    root.setAttribute("aria-labelledby", titleId);
    root.dataset.safety = action.safety;
    const main = button({
      label: action.button || buttonLabel(action),
      icon:
        action.kind === "open"
          ? "external"
          : action.safety === "destructive" || action.safety === "stops-things"
            ? ""
            : "play",
      variant:
        action.safety === "destructive"
          ? "danger"
          : action.safety === "stops-things"
            ? "danger-outline"
            : "primary",
      // acknowledged at once: busy, and deaf to more presses, until the run has started or the
      // question was answered (button() and runAction's oneQuestion)
      onClick: () => runAction(action.id, { params }),
      data: { role: "run" },
      attrs: { "aria-describedby": titleId },
    });
    const reasonText = h("span");
    const reasonFix = h("button", {
      class: "ac-fix",
      attrs: { type: "button", hidden: true },
      on: {
        click: () => {
          const current = store.action(actionId);
          const fix = store.action(current?.fixAction);
          if (!fix) return;
          // a refused entry names what to use instead: that is shown, never run from here
          if (current.safety === "refused") window.location.hash = `#/commands/${fix.id}`;
          else runAction(fix.id);
        },
      },
    });
    const reason = h(
      "p",
      { class: "ac-reason", attrs: { hidden: true } },
      icon("info", { size: 14 }),
      reasonText,
      reasonFix,
    );
    const last = h("p", { class: "ac-last", attrs: { hidden: true } });
    const paramFields = action.params.filter((p) => p.type !== "boolean");
    const what = !action.whatHappens.length
      ? action.command
        ? disclosure({
            label: "Show technical details",
            openLabel: "Hide technical details",
            content: () => h("pre", { class: "code-block", text: action.command }),
          })
        : null
      : disclosure({
          label: "What happens",
          content: () =>
            h(
              "div",
              { class: "ac-what" },
              action.whatHappens.length
                ? h(
                    "ol",
                    { class: "ac-what-list" },
                    action.whatHappens.map((line) => h("li", { text: line })),
                  )
                : null,
              action.command
                ? disclosure({
                    label: "Show technical details",
                    openLabel: "Hide technical details",
                    content: () => h("pre", { class: "code-block", text: action.command }),
                  }).el
                : null,
            ),
        });
    add(
      root,
      h(
        "div",
        { class: "ac-head" },
        showIcon
          ? h(
              "span",
              { class: "ac-icon", data: { safety: action.safety } },
              icon(actionIcon(action), { size: 20 }),
            )
          : null,
        h(
          "div",
          { class: "ac-titles" },
          h("h3", { class: "ac-title", text: action.title, attrs: { id: titleId } }),
          action.summary ? h("p", { class: "ac-summary", text: action.summary }) : null,
        ),
      ),
      h(
        "div",
        { class: "ac-meta" },
        safetyBadge(action.safety),
        action.duration
          ? h(
              "span",
              { class: "ac-duration" },
              icon("clock", { size: 14 }),
              h("span", { text: action.duration }),
            )
          : null,
        action.source === "make" ? makeSource(action) : null,
      ),
      paramFields.length
        ? h(
            "div",
            { class: "ac-params" },
            paramFields.map((p) => paramField(p, params[p.name], (v) => (params[p.name] = v))),
          )
        : null,
      h("div", { class: "ac-foot" }, what ? what.toggle : h("span"), main),
      what ? what.region : null,
      reason,
      last,
    );
    root._main = main;
    root._reason = reason;
    root._reasonText = reasonText;
    root._reasonFix = reasonFix;
    root._last = last;
    // a catalog change redraws the card; the run it is showing stays with it
    if (panel) add(root, panel.el);
    update();
  }

  function update() {
    const action = store.action(actionId);
    if (!action || !root._main) return;
    const run = store.latestRunOf(actionId);
    const can = availability(action);
    const running = run?.state === "running";
    root.dataset.state = running
      ? "running"
      : can.enabled
        ? run
          ? run.state
          : "idle"
        : "disabled";
    root._main.hidden = running;
    root._main.disabled = !can.enabled;
    root._main.dataset.disabled = String(!can.enabled);
    root._reason.hidden = can.enabled || running;
    root._reasonText.textContent = can.reason;
    // a disabled action may name the one that makes it possible ("Start the product")
    const fix =
      !can.enabled && !can.busy && action.fixAction ? store.action(action.fixAction) : null;
    root._reasonFix.hidden = !fix;
    if (fix)
      root._reasonFix.textContent =
        action.safety === "refused" ? `Go to “${fix.title}”` : fix.title;
    if (run && !running && run.finishedAt) {
      root._last.hidden = false;
      root._last.textContent = `Last run ${formatAgo(run.finishedAt)}: ${
        run.state === "ok" ? "done" : run.state === "cancelled" ? "cancelled" : "failed"
      }${run.seconds ? `, ${formatDuration(run.seconds)}` : ""}`;
    } else {
      root._last.hidden = true;
    }
    if (run && (running || run.state === "failed") && run.id !== panelRunId) {
      panel?.destroy();
      panel?.el.remove();
      panel = runPanel(run, { openOutput: action.kind === "read" });
      panelRunId = run.id;
      add(root, panel.el);
    } else if (run && run.state === "ok" && panel && panelRunId === run.id) {
      panel.update(run);
    } else if (!run && panel) {
      panel.destroy();
      panel.el.remove();
      panel = null;
      panelRunId = "";
    }
  }

  const offs = [
    store.on("actions", render),
    store.on("runs", update),
    store.on("status", update),
    store.on("connection", update),
  ];
  render();
  return {
    el: root,
    update,
    destroy() {
      offs.forEach((off) => off());
      panel?.destroy();
    },
  };
}

/** "make dev-down", and the curated action that does the same, for a make entry. */
function makeSource(action) {
  const same = action.coveredBy ? store.action(action.coveredBy) : null;
  return h(
    "span",
    { class: "ac-source" },
    h("code", { text: `make ${action.id.replace(/^make:/, "")}` }),
    same ? h("span", { text: `same as “${same.title}”` }) : null,
  );
}

function defaultParamsFor(action) {
  return defaultParams(action);
}

/** A row of plain buttons for actions (used where a whole card is too much). */
export function actionButton(
  actionId,
  { label = "", variant = "secondary", size = "md", iconName = "", params = {} } = {},
) {
  const action = store.action(actionId);
  const el = button({
    label: label || action?.title || actionId,
    icon: iconName || (action ? actionIcon(action) : "play"),
    variant,
    size,
    onClick: () => runAction(actionId, { params }),
  });
  const sync = () => {
    const current = store.action(actionId);
    const can = availability(current);
    const running = store.latestRunOf(actionId)?.state === "running";
    el.disabled = !can.enabled || running;
    el.title = running ? "Running now" : can.reason;
    el.classList.toggle("is-running", running);
  };
  const offs = [store.on("actions", sync), store.on("runs", sync), store.on("connection", sync)];
  sync();
  el._destroy = () => offs.forEach((off) => off());
  return el;
}
