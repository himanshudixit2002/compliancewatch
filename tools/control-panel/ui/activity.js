// The Activity sheet: what is running now and what ran before, each with its steps and output.

import { runPanel } from "./actions.js";
import { api } from "./api.js";
import { add, cx, formatAgo, formatDuration, h, put } from "./dom.js";
import { icon } from "./icons.js";
import * as store from "./store.js";
import { button, emptyState, spinner } from "./ui.js";

let dialog = null;
let historyLoaded = false;

export async function loadHistory(force = false) {
  if (historyLoaded && !force) return;
  try {
    store.mergeRuns(await api.runs(30));
    historyLoaded = true;
  } catch {
    // the stream still reports what runs from now on
  }
}

export function openActivity(runId = "") {
  if (dialog) {
    dialog.select(runId);
    return;
  }
  const list = h("ul", { class: "activity-list", attrs: { role: "list" } });
  let selected = runId || store.activeRun()?.id || store.state.runOrder[0] || "";
  let panel = null;
  const el = h("dialog", { class: "sheet", attrs: { "aria-labelledby": "activity-title" } });
  const close = () => {
    el.classList.add("closing");
    window.setTimeout(() => {
      if (el.open) el.close();
      el.remove();
    }, 160);
    panel?.destroy();
    off();
    dialog = null;
  };
  add(
    el,
    h(
      "div",
      { class: "sheet-head" },
      h("h2", { class: "sheet-title", text: "Activity", attrs: { id: "activity-title" } }),
      h("p", { class: "sheet-lead", text: "What this app ran since it opened, newest first." }),
      button({
        label: "Close",
        icon: "close",
        iconOnly: true,
        variant: "ghost",
        size: "sm",
        className: "sheet-close",
        onClick: close,
      }),
    ),
    h("div", { class: "sheet-body" }, list),
  );
  el.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  el.addEventListener("click", (event) => {
    if (event.target === el) close();
  });

  function draw() {
    const runs = store.state.runOrder.map((id) => store.state.runs.get(id)).filter(Boolean);
    if (!runs.length) {
      put(
        list,
        h(
          "li",
          {},
          emptyState({
            icon: "activity",
            title: "Nothing has run yet",
            body: "What you start shows here with its steps and output.",
          }),
        ),
      );
      return;
    }
    const focusedId = document.activeElement?.closest?.("[data-run]")?.dataset.run;
    put(
      list,
      ...runs.map((run) => {
        const open = run.id === selected;
        const row = h(
          "button",
          {
            class: cx("activity-row", { open }),
            attrs: { type: "button", "aria-expanded": String(open) },
            data: { run: run.id, state: run.state },
            on: {
              click: () => {
                selected = open ? "" : run.id;
                draw();
              },
            },
          },
          h(
            "span",
            { class: "activity-icon" },
            run.state === "running"
              ? spinner()
              : icon(
                  { ok: "check-circle", failed: "x-circle", cancelled: "minus-circle" }[
                    run.state
                  ] ?? "dot",
                  { size: 18 },
                ),
          ),
          h("span", { class: "activity-title", text: run.title || run.actionId }),
          h("span", {
            class: "activity-when",
            text:
              run.state === "running"
                ? "running now"
                : `${formatAgo(run.finishedAt ?? run.startedAt)}${run.seconds ? ` · ${formatDuration(run.seconds)}` : ""}`,
          }),
          icon(open ? "chevron-down" : "chevron-right", { size: 14 }),
        );
        const item = h("li", { class: "activity-item" }, row);
        if (open) {
          if (!panel || panel.runId !== run.id) {
            panel?.destroy();
            panel = runPanel(run, { showSteps: true, openOutput: true });
            panel.runId = run.id;
          }
          add(item, panel.el);
        }
        return item;
      }),
    );
    if (focusedId) list.querySelector(`[data-run="${CSS.escape(focusedId)}"]`)?.focus();
  }

  let lastShape = "";
  const off = store.on("runs", () => {
    const shape = store.state.runOrder
      .map((id) => `${id}:${store.state.runs.get(id)?.state}`)
      .join("|");
    if (shape !== lastShape) {
      lastShape = shape;
      draw();
    }
  });
  dialog = {
    select(id) {
      if (id) selected = id;
      draw();
    },
  };
  add(document.body, el);
  el.showModal();
  draw();
  loadHistory().then(draw);
  (list.querySelector(".activity-row.open") ?? el.querySelector(".sheet-close"))?.focus();
}
