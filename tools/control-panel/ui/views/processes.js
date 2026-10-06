// Processes: every port the project uses with what listens on it, and this checkout's running
// programs. A stop first shows exactly which processes it reaches.

import { oneQuestion, showRequestError } from "../actions.js";
import { api } from "../api.js";
import { add, formatAgo, formatElapsed, h, oneAtATime, plural, put } from "../dom.js";
import * as store from "../store.js";
import {
  badge,
  banner,
  button,
  emptyState,
  openDialog,
  rich,
  section,
  skeleton,
  toast,
} from "../ui.js";

export const title = "Processes";

const ORIGIN_WORDS = [
  [/^this panel \(the window\)/i, "This window", "info"],
  [/^this panel|^this app/i, "This app", "info"],
  [/^make product/i, "make product", "neutral"],
  [/^make web-stack|^panel web app/i, "The UI-only stack", "neutral"],
  [/^control panel|^another control/i, "Another control window", "warning"],
  [/agent|claude/i, "Claude's build agent", "warning"],
  [/editor/i, "An editor", "warning"],
  [/^other/i, "Another session", "warning"],
];

function origin(text) {
  if (!text) return null;
  if (/not this checkout|outside/i.test(text))
    return { label: "Not this checkout", tone: "neutral" };
  const found = ORIGIN_WORDS.find(([pattern]) => pattern.test(text));
  return found ? { label: found[1], tone: found[2] } : { label: text, tone: "neutral" };
}

export function render(root, { scope }) {
  const stamp = h("span", { class: "muted stamp", attrs: { "aria-live": "polite" } });
  const refresh = button({
    label: "Look again",
    icon: "refresh",
    size: "sm",
    onClick: () => load(),
  });
  const notice = h("div");
  const ports = h("div", { class: "card table-wrap" }, skeleton("row", 6));
  const procs = h("div", { class: "card table-wrap" }, skeleton("row", 4));
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Processes", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          rich(
            "The {ports|port} the project uses, and the programs running from this {checkout}. A stop names every {process} it reaches before anything happens and signals only those. What Claude Code or an editor runs is never stopped from here, nor is your terminal itself or anything outside this checkout.",
          ),
        ),
      ),
      h("div", { class: "view-actions" }, stamp, refresh),
    ),
    notice,
    section({
      id: "ports",
      title: "Ports",
      lead: "Who listens on each port the project uses. Docker's ports show as Colima's port forwarding.",
      children: [ports],
    }),
    section({
      id: "programs",
      title: "This checkout's programs",
      lead: "Each with how long it has run and who started it.",
      children: [procs],
    }),
  );

  let shape = "";
  let gone = false;
  scope.add(() => (gone = true));
  // one scan read at a time; a processes event that lands mid-read makes one more read after it
  const load = oneAtATime(async ({ quiet = false } = {}) => {
    if (gone) return;
    refresh.disabled = true;
    try {
      const data = await api.processes();
      if (data.loading) {
        // the first scan is still running; a processes event says when it lands
        stamp.textContent = "Looking…";
        return;
      }
      const next = JSON.stringify([data.ports, data.processes, data.error]);
      // a scan the helper pushes redraws only what changed, and keeps the keyboard's place
      if (!quiet || next !== shape) {
        shape = next;
        const focused = document.activeElement?.closest?.("[data-pid]")?.dataset.pid;
        draw(data);
        if (focused) root.querySelector(`[data-pid="${CSS.escape(focused)}"]`)?.focus();
      }
      stamp.textContent = `Looked ${formatAgo(data.taken_at ? data.taken_at * 1000 : Date.now())}`;
    } catch (e) {
      put(
        ports,
        emptyState({
          icon: "alert-circle",
          title: "The processes could not be read",
          body: e.title || e.detail || "The app's helper did not answer.",
        }),
      );
      put(procs);
    } finally {
      refresh.disabled = false;
    }
  });

  function draw(data) {
    put(
      notice,
      data.error
        ? banner({ tone: "warning", title: "Part of the scan failed", body: data.error })
        : "",
    );
    const portRows = (data.ports ?? []).map((p) => {
      const who = p.pid ? origin(p.origin) : null;
      return h(
        "tr",
        { data: { used: p.pid ? "yes" : "" } },
        h("th", { attrs: { scope: "row" } }, h("code", { text: String(p.port) })),
        h("td", { text: p.what ?? "" }),
        h("td", { class: "muted", text: p.group ?? "" }),
        h(
          "td",
          {},
          p.pid
            ? h(
                "span",
                { class: "cell-stack" },
                h(
                  "span",
                  {},
                  h("code", { text: `pid ${p.pid}` }),
                  " ",
                  h("span", { class: "cmd", text: p.command ?? "" }),
                ),
                who ? badge(who.label, who.tone) : null,
              )
            : h("span", { class: "muted", text: "Free" }),
        ),
      );
    });
    put(
      ports,
      portRows.length
        ? h(
            "table",
            { class: "table" },
            h("caption", { class: "sr-only", text: "Ports and what listens on them" }),
            h(
              "thead",
              {},
              h(
                "tr",
                {},
                ["Port", "What", "Part of", "Listening"].map((t) =>
                  h("th", { text: t, attrs: { scope: "col" } }),
                ),
              ),
            ),
            h("tbody", {}, portRows),
          )
        : emptyState({ icon: "cpu", title: "No ports to show" }),
    );
    const list = data.processes ?? [];
    const rows = list.map((p) => {
      const who = origin(p.origin);
      // the helper behind this window is never stopped from here: closing the window does it;
      // what an editor or Claude Code runs is stopped there
      const runBy = /^run by (.+)$/i.exec(p.origin ?? "");
      const stop = /\(the window\)/.test(p.origin ?? "")
        ? h("span", { class: "muted proc-self", text: "Close the window to stop it" })
        : runBy
          ? h("span", {
              class: "muted proc-self",
              text: `${runBy[1][0].toUpperCase()}${runBy[1].slice(1)} runs it; stop it there`,
            })
          : button({
              label: "Stop…",
              icon: "stop",
              size: "sm",
              variant: "danger-outline",
              attrs: { "aria-label": `Stop pid ${p.pid}, ${p.command}` },
              data: { pid: String(p.pid) },
              onClick: () => oneQuestion(`stop:${p.pid}`, () => stopFlow(p)),
            });
      return h(
        "tr",
        {},
        h("th", { attrs: { scope: "row" } }, h("code", { text: String(p.pid) })),
        h("td", { text: formatElapsed(p.elapsed) }),
        h("td", {}, who ? badge(who.label, who.tone) : null),
        h("td", { class: "cmd-cell" }, h("code", { class: "cmd", text: p.command ?? "" })),
        h("td", { class: "actions-cell" }, stop),
      );
    });
    put(
      procs,
      rows.length
        ? h(
            "table",
            { class: "table" },
            h("caption", { class: "sr-only", text: "This checkout's programs" }),
            h(
              "thead",
              {},
              h(
                "tr",
                {},
                ["Pid", "Running for", "Started by", "Command", ""].map((t, i) =>
                  h("th", {
                    text: t,
                    attrs: { scope: "col", "aria-label": i === 4 ? "Stop" : null },
                  }),
                ),
              ),
            ),
            h("tbody", {}, rows),
          )
        : emptyState({
            icon: "check-circle",
            title: "Nothing of this checkout is running",
            body: "Programs you start here or in a terminal show up while they run.",
          }),
    );
  }

  async function stopFlow(proc) {
    let preview;
    try {
      preview = await api.stopPreview(proc.pid);
    } catch (e) {
      showRequestError(e);
      return;
    }
    const options = (preview.options ?? []).filter((o) => o);
    const allowed = options.filter((o) => !o.refused && (o.pids ?? []).length);
    if (!allowed.length) {
      await openDialog({
        title: `Pid ${proc.pid} cannot be stopped from here`,
        tone: "warning",
        iconName: "shield",
        build: () => [
          h("p", {
            text: options[0]?.refused
              ? `Why: ${options[0].refused}.`
              : "Nothing it would reach belongs to this checkout.",
          }),
          h("p", {
            class: "muted",
            text: "This app never stops itself, another control window, what Claude Code or an editor runs, or anything outside this checkout.",
          }),
        ],
        actions: [{ label: "OK", value: null, variant: "primary", autofocus: true }],
      });
      return;
    }
    let mode = allowed[0].mode;
    const warnings = preview.warnings ?? [];
    const choice = await openDialog({
      title: `Stop pid ${proc.pid}?`,
      tone: "warning",
      iconName: "stop",
      size: "lg",
      build: () => {
        const name = `stop-mode-${proc.pid}`;
        const optionEls = allowed.map((o, index) =>
          h(
            "label",
            { class: "stop-option" },
            allowed.length > 1
              ? h("input", {
                  attrs: { type: "radio", name, value: o.mode },
                  props: { checked: index === 0 },
                  on: { change: () => (mode = o.mode) },
                })
              : null,
            h(
              "span",
              { class: "stop-option-body" },
              h("span", {
                class: "stop-option-title",
                text:
                  o.mode === "group"
                    ? `Its whole process group (${plural(o.pids.length, "process", "processes")})`
                    : `It and its children (${plural(o.pids.length, "process", "processes")})`,
              }),
              h(
                "ul",
                { class: "pid-list" },
                o.pids.map((p) =>
                  h(
                    "li",
                    {},
                    h("code", { text: String(p.pid ?? p) }),
                    h("span", { class: "cmd", text: p.command ?? "" }),
                    origin(p.origin) ? badge(origin(p.origin).label, origin(p.origin).tone) : null,
                  ),
                ),
              ),
            ),
          ),
        );
        return [
          h("p", {
            text: "Each process below gets a request to stop (SIGTERM); one still running the same program 5 seconds later is ended (SIGKILL). Nothing else is touched: a process that started after this list was made, or that runs another program by then, is left alone.",
          }),
          h(
            "div",
            {
              class: "stop-options",
              attrs: allowed.length > 1 ? { role: "radiogroup", "aria-label": "What to stop" } : {},
            },
            optionEls,
          ),
          ...warnings.map((w) =>
            banner({
              tone: typeof w === "object" && w.code === "sessions" ? "danger" : "warning",
              title: typeof w === "string" ? w : (w.message ?? w.title ?? ""),
              body: typeof w === "string" ? "" : (w.body ?? ""),
              role: "note",
            }),
          ),
        ];
      },
      actions: [
        { label: "Cancel", value: null, autofocus: true, key: "cancel" },
        { label: "Stop them", value: () => mode, variant: "danger", key: "confirm" },
      ],
    });
    if (!choice) return;
    try {
      await api.stopProcess(proc.pid, choice, preview.confirm_token ?? "");
      toast({
        level: "info",
        title: `Stopping pid ${proc.pid}`,
        body: "The list updates when it is done.",
      });
    } catch (e) {
      showRequestError(e);
    }
  }

  load();
  scope.add(
    store.on("run.finished", (run) => {
      if (/^stop|^process|stop$/.test(run.actionId) || run.title.toLowerCase().includes("pid"))
        load();
    }),
  );
  scope.add(store.on("processes.changed", () => load({ quiet: true })));
}
