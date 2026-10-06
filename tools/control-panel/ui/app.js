// ComplianceWatch Control: the window's entry point. It takes the token, opens the event stream,
// keeps the top bar and the sidebar current, routes between the views, and starts the tour on
// the first launch.

import { notifyRunFinished, onOpenActivity, runAction, showRequestError } from "./actions.js";
import { loadHistory, openActivity } from "./activity.js";
import { api, connectEvents, startHeartbeat, takeLaunch } from "./api.js";
import { add, cx, h, oneAtATime, plural, put } from "./dom.js";
import { GLOSSARY, PART_WORDS } from "./guide.js";
import { brandMark, icon, iconMarkup } from "./icons.js";
import { describeSession, runProgress } from "./model.js";
import { isPaletteOpen, openPalette } from "./palette.js";
import * as store from "./store.js";
import { startTour, tourRunning } from "./tour.js";
import { banner, button, mountToasts, openDialog, toast } from "./ui.js";
import * as checks from "./views/checks.js";
import * as commands from "./views/commands.js";
import * as data from "./views/data.js";
import * as features from "./views/features.js";
import * as flags from "./views/flags.js";
import * as guide from "./views/guide.js";
import * as home from "./views/home.js";
import * as logs from "./views/logs.js";
import * as pipeline from "./views/pipeline.js";
import * as processes from "./views/processes.js";
import * as run from "./views/run.js";

const VIEWS = {
  home,
  run,
  data,
  checks,
  features,
  pipeline,
  flags,
  processes,
  logs,
  commands,
  guide,
};
const APP_NAME = "ComplianceWatch Control";

const $ = (id) => document.getElementById(id);

// ---- the shell ------------------------------------------------------------------------------------

function fillIcons() {
  for (const el of document.querySelectorAll("[data-icon]")) {
    el.innerHTML = iconMarkup(el.dataset.icon, { size: Number(el.dataset.size ?? 18) });
  }
  const mark = document.querySelector(".brand-slot");
  if (mark) put(mark, brandMark());
}

function makeScope() {
  const cleanups = [];
  return {
    add(fn) {
      if (typeof fn === "function") cleanups.push(fn);
    },
    use(component) {
      if (!component) return null;
      if (component instanceof Node) {
        if (component._destroy) cleanups.push(component._destroy);
        return component;
      }
      if (component.el) {
        if (component.destroy) cleanups.push(() => component.destroy());
        return component.el;
      }
      return component;
    },
    dispose() {
      while (cleanups.length) {
        try {
          cleanups.pop()();
        } catch (error) {
          console.error(error);
        }
      }
    },
  };
}

// ---- routing --------------------------------------------------------------------------------------

let current = null;
let navigatedByUser = false;

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [view, ...params] = raw.split("/").filter(Boolean);
  return { view: VIEWS[view] ? view : "home", params };
}

function route() {
  const { view, params } = parseHash();
  if (current && current.name === view && current.controller?.update) {
    current.controller.update(params);
    return;
  }
  current?.scope.dispose();
  const main = $("main");
  const module = VIEWS[view];
  const scope = makeScope();
  const root = h("div", { class: cx("view", `view-${view}`), data: { view } });
  put(main, root);
  let controller = null;
  try {
    controller = module.render(root, { scope, params }) ?? null;
  } catch (error) {
    console.error(error);
    put(
      root,
      banner({
        tone: "danger",
        title: "This page could not be drawn",
        body: "Something in the window went wrong. Reload the app; if it keeps happening, tell a developer.",
      }),
    );
  }
  current = { name: view, scope, controller };
  document.title = `${module.title} · ${APP_NAME}`;
  for (const link of document.querySelectorAll(".nav-link")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  main.scrollTop = 0;
  if (navigatedByUser) root.querySelector(".view-title")?.focus({ preventScroll: true });
  navigatedByUser = true;
}

// ---- the top bar ------------------------------------------------------------------------------------

const PILL_PARTS = ["docker", "infra", "services", "product", "web"];

function updatePills() {
  const parts = store.state.parts;
  for (const key of PILL_PARTS) {
    const pill = document.querySelector(`.pill[data-part="${key}"]`);
    if (!pill) continue;
    const part = parts[key];
    pill.dataset.state = part.state;
    pill.querySelector(".pill-state").textContent = part.label;
    pill.setAttribute(
      "aria-label",
      `${PART_WORDS[key].title}: ${part.label}${part.detail ? `, ${part.detail}` : ""}`,
    );
    pill.title = `${PART_WORDS[key].title}: ${part.label}${part.detail ? ` (${part.detail})` : ""}`;
  }
}

function updateBranch() {
  const chip = $("branch-chip");
  const status = store.state.status;
  if (!chip || !status) return;
  const c = status.checkout;
  const sessions = status.sessions.length;
  const tone = sessions ? "danger" : c.branch && !c.isMain ? "warning" : "neutral";
  chip.dataset.tone = tone;
  chip.hidden = false;
  chip.querySelector(".branch-name").textContent = c.error
    ? "git unreadable"
    : c.branch || "unknown";
  const note = chip.querySelector(".branch-note");
  note.textContent = sessions
    ? plural(sessions, "other session")
    : c.branch && !c.isMain
      ? "not main"
      : "";
  note.hidden = !note.textContent;
  // narrower windows hide the note; a people count still says another session is at work
  const count = chip.querySelector(".branch-count");
  count.hidden = !sessions;
  count.querySelector(".branch-count-num").textContent = String(sessions);
  chip.title = sessions ? `${plural(sessions, "other session")} working in this checkout` : "";
  chip.setAttribute(
    "aria-label",
    `Checkout on ${c.branch || "an unknown branch"}${c.isMain ? "" : ", not main"}${sessions ? `, ${plural(sessions, "other session")} working in it` : ""}. Show details.`,
  );
}

function showCheckout() {
  const status = store.state.status;
  if (!status) return;
  const c = status.checkout;
  openDialog({
    title: "The checkout",
    iconName: "branch",
    tone: status.sessions.length ? "danger" : c.isMain ? "" : "warning",
    build: () => [
      h(
        "dl",
        { class: "facts" },
        h("dt", { text: "Branch" }),
        h("dd", {}, h("strong", { text: c.branch || "unknown" }), c.isMain ? "" : " (not main)"),
        h("dt", { text: "Last change" }),
        h("dd", {}, h("code", { text: c.sha }), ` ${c.subject}`, c.when ? ` · ${c.when}` : ""),
        h("dt", { text: "Uncommitted" }),
        h("dd", { text: c.dirty ? `${plural(c.dirty, "file")} changed` : "Nothing" }),
        h("dt", { text: "Against main" }),
        h("dd", {
          text:
            c.ahead === null
              ? "Unknown"
              : `${plural(c.ahead, "commit")} ahead, ${plural(c.behind, "commit")} behind origin/main`,
        }),
      ),
      c.branch && !c.isMain
        ? banner({
            tone: "warning",
            title: "Not on main",
            body: "Everything here runs this branch's code and commands. Confirms say so before anything changes.",
          })
        : null,
      status.sessions.length
        ? banner({
            tone: "danger",
            title: "Other sessions are working in this checkout",
            body: "Stopping or resetting what they use breaks their work. Wait for them if you can.",
            items: status.sessions.map(describeSession),
          })
        : null,
      h("p", {
        class: "muted",
        text: "This app reads git without changing anything: it never fetches, commits or switches branches.",
      }),
    ],
    actions: [
      { label: "See processes", value: "processes", key: "processes" },
      { label: "Close", value: null, variant: "primary", autofocus: true, key: "close" },
    ],
  }).then((choice) => {
    if (choice === "processes") window.location.hash = "#/processes";
  });
}

function updateActivityButton() {
  const btn = $("activity-btn");
  if (!btn) return;
  const run = store.activeRun();
  const label = btn.querySelector(".activity-label");
  const bar = btn.querySelector(".activity-bar");
  btn.dataset.state = run ? "running" : "";
  if (run) {
    const p = runProgress(run);
    label.textContent = p.total ? `${run.title} · ${p.index + 1}/${p.total}` : run.title;
    bar.style.setProperty("--value", `${Math.round((p.value ?? 0.1) * 100)}%`);
    btn.setAttribute(
      "aria-label",
      `Activity: ${run.title} is running${p.total ? `, step ${p.index + 1} of ${p.total}` : ""}. Show it.`,
    );
  } else {
    label.textContent = "Activity";
    btn.setAttribute("aria-label", "Activity: what ran and what is running");
  }
}

function updateConnection() {
  const bar = $("connection");
  const state = store.state.connection;
  document.body.dataset.connection = state;
  if (state === "unauthorized") {
    showLocked(
      "This window lost its key",
      "The app's helper no longer accepts this window, perhaps because it restarted. Quit ComplianceWatch Control and open it again.",
    );
    return;
  }
  bar.hidden = !["reconnecting", "offline"].includes(state);
  if (bar.hidden) return;
  put(
    bar,
    banner({
      tone: state === "offline" ? "danger" : "info",
      title:
        state === "offline"
          ? "The app's helper is not answering"
          : "Reconnecting to the app's helper",
      body:
        state === "offline"
          ? "It may have stopped, or the Mac slept. The window keeps trying; if nothing changes, quit the app and open it again."
          : "Live updates pause for a moment. Nothing that was running is affected.",
      actions:
        state === "offline"
          ? [
              button({
                label: "Try now",
                icon: "refresh",
                size: "sm",
                onClick: () => events?.reconnect(),
              }),
            ]
          : [],
    }),
  );
}

function updateDemo() {
  $("demo-chip").hidden = !store.state.hello.demo;
}

/**
 * Quit, for the window's own button: in the app, the app quits (it shows "Quitting…" and stops
 * the helper); in a browser, the helper stops and the tab says so. A task still running is
 * named first, since quitting stops it partway through.
 */
async function quitApp() {
  const running = store.activeRun();
  if (running) {
    const choice = await openDialog({
      title: `${running.title} is still running`,
      tone: "warning",
      iconName: "power",
      build: () => [
        h("p", {
          text: "Quitting stops it now, partway through. Anything it already did stays done.",
        }),
      ],
      actions: [
        { label: "Keep running", value: null, autofocus: true, key: "keep" },
        { label: "Quit and stop it", value: "quit", variant: "danger", key: "quit" },
      ],
    });
    if (choice !== "quit") return;
  }
  const bridge = window.webkit?.messageHandlers?.cwControl;
  if (bridge) {
    bridge.postMessage("quit");
    return;
  }
  try {
    await api.quit();
  } catch {
    // the helper may already be gone: the tab says it stopped either way
  }
  events?.close();
  showLocked(
    "ComplianceWatch Control has stopped",
    "You can close this tab. Open the app again to start it.",
  );
}

function showLocked(title, text) {
  const app = $("app");
  app.inert = true;
  const screen = h(
    "div",
    { class: "locked", attrs: { role: "alert" } },
    h(
      "div",
      { class: "locked-card card" },
      h("span", { class: "locked-icon" }, icon("lock", { size: 28 })),
      h("h1", { class: "locked-title", text: title }),
      h("p", { text }),
      h(
        "p",
        { class: "muted" },
        "From a terminal in the checkout, make control-panel opens a new window.",
      ),
    ),
  );
  add(document.body, screen);
}

// ---- glossary hints ------------------------------------------------------------------------------------

function setupTerms() {
  const tip = $("term-tip");
  const byId = new Map(GLOSSARY.map((g) => [g.id, g]));
  let owner = null;
  const show = (el) => {
    const entry = byId.get(el.dataset.term);
    if (!entry) return;
    owner = el;
    tip.textContent = entry.text;
    tip.hidden = false;
    el.setAttribute("aria-describedby", "term-tip");
    const r = el.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const x = Math.min(
      window.innerWidth - t.width - 8,
      Math.max(8, r.left + r.width / 2 - t.width / 2),
    );
    const y = r.bottom + 8 + t.height < window.innerHeight ? r.bottom + 8 : r.top - t.height - 8;
    tip.style.setProperty("--x", `${Math.round(x)}px`);
    tip.style.setProperty("--y", `${Math.round(y)}px`);
  };
  const hide = () => {
    tip.hidden = true;
    owner?.removeAttribute("aria-describedby");
    owner = null;
  };
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.(".term");
    if (el && el !== owner) show(el);
    else if (!el && owner) hide();
  });
  document.addEventListener("focusin", (e) => {
    const el = e.target.closest?.(".term");
    if (el) show(el);
    else if (owner) hide();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && owner) hide();
  });
  window.addEventListener("scroll", hide, true);
}

// ---- data and events ------------------------------------------------------------------------------------

let events = null;

// one read of each at a time; a request that comes mid-read makes one more read after it, so an
// older answer never lands after a newer one
const loadStatus = oneAtATime(async () => {
  try {
    store.setStatus(await api.status());
  } catch (error) {
    if (error.status === 401) store.setConnection("unauthorized");
    else store.setStatusError(error);
  }
});

const loadActions = oneAtATime(async () => {
  try {
    store.setActions(await api.actions());
  } catch (error) {
    if (error.status === 401) store.setConnection("unauthorized");
    else {
      store.setActions({ actions: [] });
      toast({
        level: "error",
        title: "The list of actions could not be read",
        body:
          error.title ||
          error.detail ||
          "The app's helper did not answer. The window tries again when it reconnects.",
      });
    }
  }
});

function onEvent(type, payload) {
  // every event is also published by name, for the views that wait on a background read
  // (features, github, processes, kafka)
  store.emit(`event:${type}`, payload);
  switch (type) {
    case "hello":
      store.setHello(payload);
      if (payload?.resync) {
        loadStatus();
        loadActions();
        loadHistory(true);
      }
      break;
    case "processes":
      store.emit("processes.changed", payload);
      break;
    case "kafka":
      store.setCache("kafka", payload);
      break;
    case "status":
      store.setStatus(payload);
      break;
    case "actions":
      if (payload && Array.isArray(payload.actions)) store.setActions(payload);
      else loadActions();
      break;
    case "run.started":
      store.runStarted(payload);
      break;
    case "run.step":
      store.runStep(payload);
      break;
    case "run.output":
      store.runOutput(payload);
      break;
    case "run.finished": {
      store.runFinished(payload);
      const finished = store.state.runs.get(String(payload.run_id));
      if (finished) notifyRunFinished(finished);
      break;
    }
    case "toast":
      // A notice about a run is the window's own (it shows run.finished with the fix and the
      // next step), so the helper's copy of it is dropped; any other notice shows as sent.
      if (payload?.run_id) break;
      toast({
        level: payload?.level ?? "info",
        title: String(payload?.title ?? ""),
        body: String(payload?.body ?? ""),
        actions:
          payload?.action && store.action(payload.action)
            ? [
                {
                  label: store.action(payload.action).title,
                  variant: "primary",
                  onClick: () => runAction(payload.action),
                },
              ]
            : [],
      });
      break;
    default:
      break;
  }
}

async function prefs() {
  try {
    return await api.prefs();
  } catch {
    try {
      return { tour_done: window.localStorage.getItem("cw-control-tour") === "done" };
    } catch {
      return { tour_done: false };
    }
  }
}

async function savePrefs(values) {
  try {
    await api.savePrefs(values);
  } catch {
    try {
      if (values.tour_done) window.localStorage.setItem("cw-control-tour", "done");
    } catch {
      // nowhere to keep it; the tour may show again next time
    }
  }
}

function tour() {
  if (tourRunning()) return;
  startTour({ onDone: () => savePrefs({ tour_done: true }) });
}

// ---- boot --------------------------------------------------------------------------------------------------

async function boot() {
  // every file arrived: a later load that loses one may reload once again (boot.js)
  try {
    window.sessionStorage.removeItem("cw-control-reloaded");
  } catch {
    // no session storage: boot.js then never reloads
  }
  fillIcons();
  mountToasts($("toasts"), $("announcer"));
  if (!(await takeLaunch())) {
    showLocked(
      "Open this window from the app",
      "This page needs the key ComplianceWatch Control gives it when it opens, and the link it opened with works once, for 30 seconds. Open the app again from your Applications or Desktop.",
    );
    return;
  }
  onOpenActivity((id) => openActivity(id));
  guide.onStartTour(tour);
  window.addEventListener("cw:tour", tour);
  setupTerms();

  // The skip link moves focus without touching the address: the fragment holds the route.
  document.querySelector(".skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    $("main").focus();
  });
  $("palette-btn").addEventListener("click", () => openPalette());
  $("activity-btn").addEventListener("click", () => openActivity());
  $("branch-chip").addEventListener("click", showCheckout);
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (!isPaletteOpen() && !tourRunning()) openPalette();
    }
  });
  for (const link of document.querySelectorAll(".nav-link")) {
    link.addEventListener("click", () => {
      navigatedByUser = true;
    });
  }

  store.on("parts", updatePills);
  store.on("status", updateBranch);
  store.on("runs", updateActivityButton);
  store.on("connection", updateConnection);
  store.on("hello", updateDemo);
  store.on("status", updateDemo);

  window.addEventListener("hashchange", route);
  navigatedByUser = false;
  route();

  events = connectEvents({
    onEvent,
    onState: (state) => store.setConnection(state),
    onOpen: () => {
      loadStatus();
      loadActions();
    },
  });
  // one stream per window, and none while it is hidden or after it went away: a reload or a
  // window closed into the background leaves no stream behind in the helper
  if (document.visibilityState === "hidden") events.pause();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") events?.pause();
    else events?.resume();
  });
  window.addEventListener("pagehide", (event) => {
    if (event.persisted) events?.pause();
    else events?.close();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) events?.resume();
  });
  $("quit-btn")?.addEventListener("click", () => quitApp());
  Promise.all([loadStatus(), loadActions()]).then(async () => {
    loadHistory();
    const saved = await prefs();
    store.state.prefs = saved ?? {};
    if (!saved?.tour_done && store.state.connection !== "unauthorized") {
      window.setTimeout(() => {
        if (window.location.hash.startsWith("#/home") || !window.location.hash) tour();
      }, 500);
    }
  });
  startHeartbeat((ok, error) => {
    if (!ok && error?.status === 401) store.setConnection("unauthorized");
  });
  window.addEventListener("unhandledrejection", (event) => {
    if (event.reason?.code) showRequestError(event.reason);
  });
}

boot();
