// Checks: the same checks CI runs, the product check, and the result of each in this window.

import { add, formatAgo, formatDuration, h, put } from "../dom.js";
import * as store from "../store.js";
import { rich, statusChip } from "../ui.js";
import { actionSections, place, revealSection } from "./common.js";

export const title = "Checks";

function gateIds() {
  return store.state.actions
    .filter((a) => a.id.startsWith("gate:") && a.id !== "gate:check")
    .map((a) => a.id);
}

const SECTIONS = [
  {
    id: "share",
    title: "Before you share work",
    lead: () =>
      rich(
        "The quick checks are what {CI} runs before Docker: code style, types, tests and the project's own rules. Every CI check in order needs Docker and takes much longer.",
      ),
    actions: ["gate:check", "gates-in-order"],
  },
  {
    id: "product",
    title: "The product",
    lead: () =>
      rich(
        "The {product check} proves the running product works, step by step; pick one step to run it alone. The web journey clicks through the product's web app. Both need the product running.",
      ),
    actions: ["product-check", "product-e2e"],
  },
  {
    id: "one",
    title: "One check at a time",
    lead: "Run a single check again after you fix what it found.",
    rows: true,
    actions: () => gateIds(),
  },
  {
    id: "results",
    title: "Results in this window",
    lead: "The last result of each check you ran since the app opened.",
    actions: [],
    extra: (scope) => resultsTable(scope),
  },
];

place("checks", ["gate:check", "gates-in-order", "product-check", "product-e2e"]);

export function render(root, { scope, params }) {
  place("checks", gateIds());
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Checks", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "The same checks CI runs on every change. Run them before you share work, so nothing fails later that you could have seen now.",
        ),
      ),
    ),
  );
  actionSections(root, scope, "checks", SECTIONS);
  revealSection(root, params[0]);
  return { update: (next) => revealSection(root, next[0]) };
}

function resultsTable(scope) {
  const body = h("tbody");
  const empty = h("p", { class: "muted", text: "No check has run in this window yet." });
  const table = h(
    "table",
    { class: "table" },
    h("caption", { class: "sr-only", text: "The last result of each check" }),
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ["Check", "Result", "Took", "When"].map((text) =>
          h("th", { text, attrs: { scope: "col" } }),
        ),
      ),
    ),
    body,
  );
  const wrap = h("div", { class: "card table-wrap" }, empty, table);
  const isCheck = (id) =>
    id.startsWith("gate") ||
    id.startsWith("product-check") ||
    id === "product-e2e" ||
    id === "flags-check";
  const sync = () => {
    const seen = new Map();
    for (const id of store.state.runOrder) {
      const run = store.state.runs.get(id);
      if (run && isCheck(run.actionId) && !seen.has(run.actionId)) seen.set(run.actionId, run);
    }
    empty.hidden = seen.size > 0;
    table.hidden = seen.size === 0;
    put(
      body,
      ...[...seen.values()].map((run) =>
        h(
          "tr",
          { data: { state: run.state } },
          h("th", { text: run.title, attrs: { scope: "row" } }),
          h(
            "td",
            {},
            statusChip(
              run.state === "ok"
                ? "running"
                : run.state === "running"
                  ? "busy"
                  : run.state === "failed"
                    ? "problem"
                    : "stopped",
              { ok: "Passed", running: "Running", failed: "Failed", cancelled: "Cancelled" }[
                run.state
              ] ?? run.state,
            ),
          ),
          h("td", { text: run.seconds ? formatDuration(run.seconds) : "" }),
          h("td", { text: formatAgo(run.finishedAt ?? run.startedAt) }),
        ),
      ),
    );
  };
  sync();
  scope.add(store.on("runs", sync));
  return wrap;
}
