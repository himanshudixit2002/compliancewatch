// Logs: the end of each log the project writes (the services, the product, the workers and
// relays, the web app and the containers), a bounded number of lines at a time.

import { api } from "../api.js";
import { add, cx, formatAgo, h, plural, put } from "../dom.js";
import { icon } from "../icons.js";
import { normalizeLine } from "../model.js";
import * as store from "../store.js";
import { actionButton } from "../actions.js";
import { button, copyButton, emptyState, outputView, skeleton } from "../ui.js";

export const title = "Logs";

const TAILS = [200, 500, 2000];

function normalizeSources(raw) {
  return (raw?.sources ?? raw ?? []).map((s) => ({
    id: String(s.id ?? s.key ?? ""),
    label: String(s.label ?? s.id ?? ""),
    group: String(s.group ?? "Logs"),
    path: String(s.path ?? ""),
    available: (s.available ?? s.exists) !== false,
  }));
}

export function render(root, { scope, params }) {
  let sources = [];
  let current = params[0] ? decodeURIComponent(params[0]) : "";
  let tail = 500;
  let filterText = "";
  let lastLines = [];
  const nav = h(
    "nav",
    { class: "log-sources card", attrs: { "aria-label": "Logs" } },
    skeleton("line", 8),
  );
  const heading = h("h2", { class: "log-title", text: "Choose a log", attrs: { id: "log-title" } });
  const path = h("p", { class: "log-path muted" });
  const stamp = h("span", { class: "muted stamp", attrs: { "aria-live": "polite" } });
  const output = outputView({ label: "Log lines", max: 5000 });
  const filter = h("input", {
    class: "input search-input",
    attrs: {
      type: "search",
      placeholder: "Find in this log",
      "aria-label": "Find in this log",
      autocomplete: "off",
    },
    on: {
      input: (e) => {
        filterText = e.target.value.trim().toLowerCase();
        show();
      },
    },
  });
  const tailSelect = h(
    "select",
    {
      class: "select select-sm",
      attrs: { "aria-label": "How many lines" },
      on: {
        change: (e) => {
          tail = Number(e.target.value);
          load();
        },
      },
    },
    TAILS.map((n) =>
      h("option", { text: `Last ${n} lines`, props: { value: String(n), selected: n === tail } }),
    ),
  );
  const follow = h("input", {
    attrs: { type: "checkbox", id: "log-follow" },
    props: { checked: true },
    on: { change: (e) => output.setFollow(e.target.checked) },
  });
  const refresh = button({ label: "Refresh", icon: "refresh", size: "sm", onClick: () => load() });
  const viewer = h(
    "section",
    { class: "card log-viewer", attrs: { "aria-labelledby": "log-title" } },
    h(
      "div",
      { class: "log-head" },
      h("div", {}, heading, path),
      h("div", { class: "log-tools" }, stamp, refresh),
    ),
    h(
      "div",
      { class: "toolbar log-toolbar" },
      filter,
      tailSelect,
      h(
        "label",
        { class: "check-field", attrs: { for: "log-follow" } },
        follow,
        h("span", { text: "Keep at the latest line" }),
      ),
      copyButton(() => output.text(), { label: "Copy", variant: "secondary" }),
    ),
    output.el,
  );
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Logs", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "What each part wrote last. Logs show the end of each file when you open them; Refresh reads the newest lines.",
        ),
      ),
      store.action("open-logs-folder")
        ? h(
            "div",
            { class: "view-actions" },
            scope.use(
              actionButton("open-logs-folder", {
                label: "Open the logs folder",
                iconName: "folder",
                size: "sm",
              }),
            ),
          )
        : null,
    ),
    h("div", { class: "logs-layout" }, nav, viewer),
  );

  function drawNav() {
    if (!sources.length) {
      put(
        nav,
        emptyState({
          icon: "logs",
          title: "No logs yet",
          body: "Logs appear once a part has run.",
        }),
      );
      return;
    }
    const groups = new Map();
    for (const s of sources) {
      if (!groups.has(s.group)) groups.set(s.group, []);
      groups.get(s.group).push(s);
    }
    put(
      nav,
      ...[...groups].map(([group, items]) =>
        h(
          "div",
          { class: "log-group" },
          h("p", { class: "log-group-title", text: group }),
          h(
            "ul",
            { attrs: { role: "list" } },
            items.map((s) =>
              h(
                "li",
                {},
                h(
                  "a",
                  {
                    class: cx("log-link", { "is-off": !s.available }),
                    attrs: {
                      href: `#/logs/${encodeURIComponent(s.id)}`,
                      "aria-current": s.id === current ? "page" : null,
                    },
                  },
                  icon("logs", { size: 14 }),
                  h("span", { text: s.label }),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  function show() {
    const lines = filterText
      ? lastLines.filter((l) => l.text.toLowerCase().includes(filterText))
      : lastLines;
    output.reset(lines);
    if (filterText) stamp.textContent = `${plural(lines.length, "line")} match`;
  }

  async function load() {
    const source = sources.find((s) => s.id === current);
    if (!source) {
      heading.textContent = "Choose a log";
      path.textContent = sources.length ? "Pick one on the left." : "";
      output.reset([]);
      return;
    }
    heading.textContent = source.label;
    path.textContent = source.path;
    refresh.disabled = true;
    stamp.textContent = "Reading…";
    try {
      const data = await api.log(source.id, tail);
      lastLines = (data.lines ?? []).map((l) => normalizeLine(l));
      if (data.error) lastLines.unshift({ text: String(data.error), tag: "err" });
      show();
      stamp.textContent = `${plural(lastLines.length, "line")}${data.truncated ? ` (the last ${tail})` : ""}, read ${formatAgo(Date.now())}`;
      if (!lastLines.length) output.reset([{ text: "This log is empty.", tag: null }]);
    } catch (e) {
      lastLines = [];
      output.reset([{ text: e.title || e.detail || "The log could not be read.", tag: "err" }]);
      stamp.textContent = "";
    } finally {
      refresh.disabled = false;
    }
  }

  async function init() {
    try {
      const data = await api.logSources();
      sources = normalizeSources(data);
      store.setCache("logs", data);
    } catch (e) {
      put(
        nav,
        emptyState({
          icon: "alert-circle",
          title: "The logs could not be listed",
          body: e.title || e.detail || "",
        }),
      );
      return;
    }
    if (!current && sources.length) current = sources.find((s) => s.available)?.id ?? sources[0].id;
    drawNav();
    load();
  }

  init();
  return {
    update(nextParams) {
      const next = nextParams[0] ? decodeURIComponent(nextParams[0]) : "";
      if (next && next !== current) {
        current = next;
        drawNav();
        load();
      }
    },
  };
}
