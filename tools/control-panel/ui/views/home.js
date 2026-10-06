// Home: one big Start or Stop, the parts as a live diagram, quick tasks, recent activity and
// the code the stack runs.

import { availability, openUrl, runAction, runPanel, showActivity, targetUrl } from "../actions.js";
import {
  add,
  cx,
  formatAgo,
  formatDuration,
  h,
  plural,
  put,
  reducedMotion,
  sentence,
} from "../dom.js";
import { PART_WORDS } from "../guide.js";
import { icon } from "../icons.js";
import { checkoutWarnings, describeSession, overallState } from "../model.js";
import * as store from "../store.js";
import { badge, banner, button, rich, safetyBadge, statusChip } from "../ui.js";

export const title = "Home";

export function render(root, { scope }) {
  add(
    root,
    h("h1", { class: "sr-only view-title", text: "Home", attrs: { tabindex: "-1" } }),
    scope.use(hero()),
    scope.use(diagram()),
    h("div", { class: "home-grid" }, scope.use(quickTasks()), scope.use(recent())),
    scope.use(checkoutCard()),
  );
}

// ---- the hero ------------------------------------------------------------------------------------

const START_STAGES = [
  { part: "docker", text: "Docker" },
  { part: "infra", text: "Databases and queues" },
  { part: "services", text: "The ten services" },
  { part: "web", text: "The web app" },
];

function hero() {
  const el = h("section", {
    class: "card hero",
    attrs: { "data-tour": "hero", "aria-labelledby": "hero-title" },
  });
  let panel = null;
  let panelRun = "";
  let lastKey = "";

  function describePartial(parts) {
    const phrase = {
      docker: "Docker",
      infra: "the databases and queues",
      services: "the services",
      web: "the web app",
      product: "the product",
    };
    const up = [];
    const down = [];
    for (const key of ["docker", "infra", "services", "web", "product"]) {
      const words = phrase[key];
      if (parts[key].state === "running") up.push(words);
      else if (parts[key].state === "partial") up.push(`part of ${words}`);
      else if (key !== "product") down.push(words);
    }
    const list = (items) =>
      items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items.at(-1)}` : items[0];
    const first = up.length ? `${sentence(list(up))} ${up.length > 1 ? "are" : "is"} running` : "";
    const second = down.length ? `${list(down)} ${down.length > 1 ? "are" : "is"} not` : "";
    return `${[first, second].filter(Boolean).join("; ")}.`;
  }

  function update() {
    const parts = store.state.parts;
    const run = store.activeRun();
    const startRun = store.latestRunOf("start-everything");
    const stopRun = store.latestRunOf("stop-everything");
    const recentFailure = [startRun, stopRun]
      .filter((r) => r && r.state === "failed")
      .sort((a, b) => (b.finishedAt ?? 0) - (a.finishedAt ?? 0))[0];
    let mode = overallState(parts, run);
    const heroRun =
      run && ["start-everything", "stop-everything"].includes(run.actionId)
        ? run
        : recentFailure && Date.now() / 1000 - (recentFailure.finishedAt ?? 0) < 900
          ? recentFailure
          : null;
    if (heroRun && heroRun.state === "failed") mode = "failed";
    const key = `${mode}|${heroRun?.id ?? ""}|${parts.web.state}|${parts.product.state}|${store.state.actionsLoaded}`;
    el.dataset.state = mode;
    if (key === lastKey) return;
    lastKey = key;
    if (panel && (!heroRun || heroRun.id !== panelRun)) {
      panel.destroy();
      panel = null;
      panelRun = "";
    }
    const start = store.action("start-everything");
    const stop = store.action("stop-everything");
    const startButton = (variant = "primary") =>
      button({
        label: "Start everything",
        icon: "play",
        variant,
        size: "lg",
        onClick: () => runAction("start-everything"),
        data: { role: "start-everything" },
        attrs: { "aria-describedby": "hero-text" },
      });
    const stopButton = (variant = "danger-outline") =>
      button({
        label: "Stop everything",
        icon: "power",
        variant,
        size: "lg",
        onClick: () => runAction("stop-everything"),
        data: { role: "stop-everything" },
      });
    let eyebrow = "On this Mac";
    let titleText = "";
    let text = [];
    let buttons = [];
    let side = null;
    if (mode === "unknown") {
      titleText = "Checking what is running";
      text = ["This takes a moment the first time."];
      side = stages(parts);
    } else if (mode === "stopped") {
      titleText = "Everything is stopped";
      text = rich(
        "Start everything runs ComplianceWatch on this Mac: {Docker}, the databases and queues, the ten {services|service} and the web app. Then it opens the app in your browser.",
      );
      buttons = [startButton()];
      side = stages(parts);
    } else if (mode === "running") {
      const both = parts.web.state === "running" && parts.product.state === "running";
      titleText =
        parts.web.state === "running"
          ? "ComplianceWatch is running"
          : "The full product is running";
      text = [
        parts.web.state === "running"
          ? `The web app is at localhost:${store.state.status?.web.port ?? 3000}${both ? ", and the full product at 127.0.0.1:3400" : ""}. `
          : "Its web app is at 127.0.0.1:3400. ",
        "Stop everything when you are done to free memory; your data is kept.",
      ];
      buttons = [
        parts.web.state === "running"
          ? button({
              label: "Open the app",
              icon: "external",
              variant: "primary",
              size: "lg",
              onClick: () => openUrl(targetUrl("web").url),
              attrs: { "aria-label": "Open the app (opens in your browser)" },
            })
          : button({
              label: "Open the product",
              icon: "external",
              variant: "primary",
              size: "lg",
              onClick: () => openUrl(targetUrl("signin").url),
              attrs: { "aria-label": "Open the product (opens in your browser)" },
            }),
        stopButton(),
      ];
      side = stages(parts, true);
    } else if (mode === "partial") {
      titleText = "Some parts are running";
      text = [
        describePartial(parts),
        " Start everything starts the rest; Stop everything stops it all.",
      ];
      buttons = [startButton(), stopButton()];
      side = stages(parts);
    } else if (mode === "starting" || mode === "stopping") {
      eyebrow = mode === "starting" ? "Starting" : "Stopping";
      titleText = mode === "starting" ? "Starting ComplianceWatch" : "Stopping everything";
      text = [
        mode === "starting"
          ? "Each part starts in turn. You can keep using this app while it works."
          : "Each part stops in turn. Your data is kept.",
      ];
    } else if (mode === "failed") {
      eyebrow = "Something went wrong";
      titleText =
        heroRun.actionId === "start-everything"
          ? "Start everything did not finish"
          : "Stop everything did not finish";
      text = ["Below is what went wrong, in plain words, and what to do about it."];
      buttons = [
        heroRun.actionId === "start-everything"
          ? startButton("secondary")
          : stopButton("secondary"),
      ];
    }
    const meta =
      mode === "stopped" || mode === "partial"
        ? h(
            "p",
            { class: "hero-meta" },
            start?.duration
              ? h("span", {}, icon("clock", { size: 14 }), h("span", { text: start.duration }))
              : null,
            start ? safetyBadge(start.safety) : null,
            h("span", { text: "Nothing is deleted." }),
          )
        : null;
    if ((mode === "starting" || mode === "stopping" || mode === "failed") && heroRun) {
      if (!panel) {
        panel = runPanel(heroRun, { showSteps: true });
        panelRun = heroRun.id;
      }
      side = panel.el;
    }
    const missing = !start || !stop;
    put(
      el,
      h(
        "div",
        { class: "hero-main" },
        h("p", { class: "eyebrow", text: eyebrow }),
        h("h2", { class: "hero-title", text: titleText, attrs: { id: "hero-title" } }),
        h("p", { class: "hero-text", attrs: { id: "hero-text" } }, text),
        buttons.length ? h("div", { class: "hero-actions" }, buttons) : null,
        meta,
        missing && store.state.actionsLoaded
          ? banner({
              tone: "warning",
              title: "Start and stop are missing",
              body: "This version of the app's helper does not offer them. Commands lists what it does offer.",
            })
          : null,
      ),
      h("div", { class: "hero-side" }, side),
    );
    syncButtons();
  }

  function syncButtons() {
    for (const btn of el.querySelectorAll(
      "[data-role='start-everything'], [data-role='stop-everything']",
    )) {
      const can = availability(store.action(btn.dataset.role));
      btn.disabled = !can.enabled;
      btn.title = can.reason;
    }
  }

  const offs = [
    store.on("parts", update),
    store.on("runs", update),
    store.on("actions", () => {
      lastKey = "";
      update();
    }),
    store.on("connection", syncButtons),
  ];
  update();
  return {
    el,
    destroy() {
      offs.forEach((off) => off());
      panel?.destroy();
    },
  };
}

function stages(parts, running = false) {
  return h(
    "div",
    { class: "stages" },
    h("p", { class: "stages-title", text: running ? "What is running" : "What starts, in order" }),
    h(
      "ol",
      { class: "stage-list" },
      START_STAGES.map((stage, index) => {
        const part = parts[stage.part];
        return h(
          "li",
          { class: "stage", data: { state: part.state } },
          h("span", {
            class: "stage-num",
            text: String(index + 1),
            attrs: { "aria-hidden": "true" },
          }),
          h("span", { class: "stage-text", text: stage.text }),
          statusChip(part.state, part.label),
        );
      }),
    ),
  );
}

// ---- the diagram -----------------------------------------------------------------------------------

const NODES = [
  { part: "docker", area: "docker" },
  { part: "infra", area: "infra" },
  { part: "services", area: "services" },
  { part: "web", area: "web" },
  { part: "product", area: "product" },
];

const WIRES = [
  ["docker", "infra"],
  ["infra", "services"],
  ["infra", "product"],
  ["services", "web"],
];

const NODE_TEXT = {
  docker: "Runs the databases and the queue",
  infra: "Postgres, Redis, Redpanda, Temporal",
  services: "Ten services on 8001 to 8010",
  web: "The screens, at localhost:3000",
  product: "App, worker and web app on 3400",
};

function diagram() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "wires");
  svg.setAttribute("aria-hidden", "true");
  const nodes = new Map();
  const list = h("ul", { class: "nodes", attrs: { role: "list" } });
  for (const node of NODES) {
    const words = PART_WORDS[node.part];
    const stateEl = h("span", { class: "node-state" });
    const detailEl = h("span", { class: "node-detail" });
    const itemsEl = h("span", { class: "node-items", attrs: { "aria-hidden": "true" } });
    const btn = h(
      "a",
      {
        class: "node",
        attrs: { href: `#/run/${node.part}` },
        data: { part: node.part },
      },
      h(
        "span",
        { class: "node-top" },
        h("span", { class: "node-icon" }, icon(words.icon, { size: 20 })),
        stateEl,
      ),
      h("span", { class: "node-title", text: words.title }),
      h("span", { class: "node-text", text: NODE_TEXT[node.part] }),
      itemsEl,
      detailEl,
    );
    const li = h("li", { class: "node-cell", data: { area: node.area } }, btn);
    nodes.set(node.part, { li, btn, stateEl, detailEl, itemsEl });
    add(list, li);
  }
  const extras = h("p", { class: "diagram-extras" });
  const canvas = h("div", { class: "diagram" }, svg, list);
  const legend = h(
    "ul",
    { class: "legend", attrs: { "aria-label": "Colours" } },
    [
      ["running", "Running"],
      ["partial", "Partly running"],
      ["busy", "Starting or stopping"],
      ["stopped", "Stopped"],
      ["problem", "Needs attention"],
    ].map(([state, text]) =>
      h(
        "li",
        { data: { state } },
        h("span", { class: "dot", attrs: { "aria-hidden": "true" } }),
        text,
      ),
    ),
  );
  const el = h(
    "section",
    {
      class: "card diagram-card",
      attrs: { "data-tour": "diagram", "aria-labelledby": "diagram-title" },
    },
    h(
      "div",
      { class: "card-head" },
      h(
        "div",
        {},
        h("h2", { class: "card-title", text: "What is running", attrs: { id: "diagram-title" } }),
        h("p", {
          class: "card-lead",
          text: "Each part, as it is now. Choose one to start or stop it on its own.",
        }),
      ),
      legend,
    ),
    canvas,
    extras,
  );

  function update() {
    const parts = store.state.parts;
    for (const [part, refs] of nodes) {
      const p = parts[part];
      refs.li.dataset.state = p.state;
      refs.btn.dataset.state = p.state;
      put(refs.stateEl, statusChip(p.state, p.label));
      refs.btn.setAttribute(
        "aria-label",
        `${PART_WORDS[part].title}: ${p.label}. ${NODE_TEXT[part]}. Open its controls.`,
      );
      let detail = "";
      if (part === "services" && p.total) detail = p.detail;
      if (part === "infra") detail = p.detail;
      if (part === "product" && p.items?.length)
        detail = p.items.map((i) => `${i.label} ${i.up ? "up" : "down"}`).join(" · ");
      refs.detailEl.textContent = detail;
      if (part === "services" || part === "infra") {
        const items = part === "services" ? p.items : p.items;
        put(
          refs.itemsEl,
          ...(items ?? []).map((item) =>
            h("span", {
              class: "mini-dot",
              data: {
                state:
                  part === "services"
                    ? item.up
                      ? "running"
                      : item.up === null
                        ? "unknown"
                        : "stopped"
                    : item.state,
              },
              attrs: { title: item.name ?? item.label },
            }),
          ),
        );
      }
    }
    const status = store.state.status;
    const bits = [];
    const running = status?.background.filter((b) => b.pid) ?? [];
    if (running.length)
      bits.push(`${plural(running.length, "worker or relay", "workers and relays")} running`);
    const toolsUp = (status?.infra ?? [])
      .filter((c) => c.profile && c.up)
      .map((c) => c.label || c.service);
    if (toolsUp.length) bits.push(`Optional tools: ${toolsUp.join(", ")}`);
    extras.textContent = bits.join(" · ");
    extras.hidden = bits.length === 0;
    drawWires();
  }

  function drawWires() {
    const base = canvas.getBoundingClientRect();
    if (!base.width) return;
    const parts = store.state.parts;
    const paths = WIRES.map(([from, to]) => {
      const a = nodes.get(from).btn.getBoundingClientRect();
      const b = nodes.get(to).btn.getBoundingClientRect();
      let d;
      if (b.left >= a.right - 2) {
        const y1 = Math.min(Math.max(b.top + b.height / 2, a.top + 16), a.bottom - 16) - base.top;
        const y2 = b.top + b.height / 2 - base.top;
        const x1 = a.right - base.left;
        const x2 = b.left - base.left;
        const mid = (x1 + x2) / 2;
        d = `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
      } else {
        const x1 = Math.min(Math.max(b.left + b.width / 2, a.left + 16), a.right - 16) - base.left;
        const x2 = b.left + Math.min(b.width / 2, 48) - base.left;
        const y1 = a.bottom - base.top;
        const y2 = b.top - base.top;
        const mid = (y1 + y2) / 2;
        d = `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`;
      }
      const live =
        parts[from].state === "running" && ["running", "partial", "busy"].includes(parts[to].state);
      const busy = parts[to].state === "busy" || parts[from].state === "busy";
      return `<path class="${cx("wire", { live, busy, still: reducedMotion() })}" d="${d}"/>`;
    });
    svg.setAttribute("viewBox", `0 0 ${base.width} ${base.height}`);
    svg.setAttribute("width", String(base.width));
    svg.setAttribute("height", String(base.height));
    svg.innerHTML = paths.join("");
  }

  const observer = new ResizeObserver(() => drawWires());
  observer.observe(canvas);
  const off = store.on("parts", update);
  update();
  window.requestAnimationFrame(drawWires);
  return {
    el,
    destroy() {
      off();
      observer.disconnect();
    },
  };
}

// ---- quick tasks -------------------------------------------------------------------------------------

const QUICK = [
  {
    id: "open-app",
    icon: "globe",
    title: "Open the app",
    text: "The web app, in your browser",
    open: "web",
  },
  {
    id: "load-demo-data",
    icon: "sparkles",
    title: "Load demo data",
    text: "A demo business and the GST rules",
    action: "load-demo-data",
  },
  {
    id: "gate:check",
    icon: "checks",
    title: "Run the checks",
    text: "What CI runs before Docker",
    action: "gate:check",
  },
  {
    id: "stop-everything",
    icon: "power",
    title: "Free up memory",
    text: "Stop everything; data is kept",
    action: "stop-everything",
  },
];

function quickTasks() {
  const tiles = QUICK.map((task) => {
    const state = h("span", { class: "tile-state" });
    const reason = h("span", { class: "tile-reason" });
    const tile = h(
      "button",
      {
        class: "tile",
        attrs: { type: "button" },
        data: { task: task.id },
        on: {
          click: () => {
            if (task.open) {
              const target = targetUrl(task.open);
              openUrl(target.url);
            } else runAction(task.action);
          },
        },
      },
      h("span", { class: "tile-icon" }, icon(task.icon, { size: 22 })),
      h("span", { class: "tile-title", text: task.title }),
      h("span", { class: "tile-text", text: task.text }),
      state,
      reason,
    );
    return { task, tile, state, reason };
  });
  const el = h(
    "section",
    { class: "card quick", attrs: { "aria-labelledby": "quick-title" } },
    h(
      "div",
      { class: "card-head" },
      h("h2", { class: "card-title", text: "Quick tasks", attrs: { id: "quick-title" } }),
    ),
    h(
      "div",
      { class: "tiles" },
      tiles.map((t) => t.tile),
    ),
  );
  function update() {
    for (const { task, tile, state, reason } of tiles) {
      if (task.open) {
        const target = targetUrl(task.open);
        tile.disabled = !target.up;
        reason.textContent = target.up ? "" : "Start everything first";
        tile.setAttribute(
          "aria-label",
          `${task.title}: ${task.text}${target.up ? " (opens in your browser)" : ". Start everything first."}`,
        );
        continue;
      }
      const action = store.action(task.action);
      const can = availability(action);
      const run = store.latestRunOf(task.action);
      const running = run?.state === "running";
      tile.disabled = !can.enabled || running;
      tile.dataset.state = running ? "running" : "";
      put(state, running ? h("span", { class: "spinner", attrs: { "aria-hidden": "true" } }) : "");
      reason.textContent = running ? "Running now" : can.enabled ? "" : can.reason;
      tile.setAttribute(
        "aria-label",
        `${task.title}: ${task.text}${running ? ". Running now" : can.enabled ? "" : `. ${can.reason}`}`,
      );
    }
  }
  const offs = [
    store.on("parts", update),
    store.on("runs", update),
    store.on("actions", update),
    store.on("connection", update),
  ];
  update();
  return { el, destroy: () => offs.forEach((off) => off()) };
}

// ---- recent activity ----------------------------------------------------------------------------------

function recent() {
  const list = h("ul", { class: "recent-list", attrs: { role: "list" } });
  const el = h(
    "section",
    { class: "card recent", attrs: { "aria-labelledby": "recent-title" } },
    h(
      "div",
      { class: "card-head" },
      h("h2", { class: "card-title", text: "Recent activity", attrs: { id: "recent-title" } }),
      button({ label: "Show all", size: "sm", variant: "ghost", onClick: () => showActivity() }),
    ),
    list,
  );
  function update() {
    const runs = store.state.runOrder
      .map((id) => store.state.runs.get(id))
      .filter((run) => run && store.action(run.actionId)?.kind !== "read")
      .slice(0, 5);
    if (!runs.length) {
      put(
        list,
        h("li", {
          class: "recent-empty",
          text: "Nothing has run yet. What you start shows here, with how it went.",
        }),
      );
      return;
    }
    put(
      list,
      ...runs.map((run) =>
        h(
          "li",
          {},
          h(
            "button",
            {
              class: "recent-item",
              attrs: { type: "button" },
              data: { state: run.state },
              on: { click: () => showActivity(run.id) },
            },
            h(
              "span",
              { class: "recent-icon" },
              run.state === "running"
                ? h("span", { class: "spinner", attrs: { "aria-hidden": "true" } })
                : icon(
                    run.state === "ok"
                      ? "check-circle"
                      : run.state === "cancelled"
                        ? "minus-circle"
                        : "x-circle",
                    { size: 18 },
                  ),
            ),
            h("span", { class: "recent-title", text: run.title }),
            h("span", {
              class: "recent-when",
              text:
                run.state === "running"
                  ? "running now"
                  : `${{ ok: "done", failed: "failed", cancelled: "cancelled" }[run.state] ?? run.state} ${formatAgo(run.finishedAt ?? run.startedAt)}${run.seconds ? ` · ${formatDuration(run.seconds)}` : ""}`,
            }),
          ),
        ),
      ),
    );
  }
  const offs = [store.on("runs", update), store.on("actions", update)];
  update();
  return { el, destroy: () => offs.forEach((off) => off()) };
}

// ---- the code ------------------------------------------------------------------------------------------

function checkoutCard() {
  const body = h("div", { class: "checkout-body" });
  const el = h(
    "section",
    { class: "card checkout", attrs: { "aria-labelledby": "checkout-title" } },
    h(
      "div",
      { class: "card-head" },
      h(
        "div",
        {},
        h("h2", { class: "card-title", text: "The code it runs", attrs: { id: "checkout-title" } }),
        h(
          "p",
          { class: "card-lead" },
          rich("The {checkout} this app controls, read without changing anything."),
        ),
      ),
    ),
    body,
  );
  function update() {
    const status = store.state.status;
    if (!status) {
      put(
        body,
        h("span", { class: "skel skel-line" }),
        h("span", { class: "skel skel-line short" }),
      );
      return;
    }
    const c = status.checkout;
    if (c.error) {
      put(body, banner({ tone: "warning", title: "git cannot read this checkout", body: c.error }));
      return;
    }
    const rows = [
      [
        "Branch",
        h(
          "span",
          { class: "branch-inline" },
          icon("branch", { size: 14 }),
          h("strong", { text: c.branch || "unknown" }),
          c.isMain ? badge("main", "success") : badge("not main", "warning"),
        ),
      ],
      [
        "Last change",
        h(
          "span",
          {},
          h("code", { text: c.sha }),
          " ",
          c.subject,
          c.when ? h("span", { class: "muted", text: ` · ${c.when}` }) : null,
        ),
      ],
      [
        "Uncommitted",
        c.dirty ? `${plural(c.dirty, "file")} changed and not committed` : "Nothing uncommitted",
      ],
      [
        "Against main",
        c.ahead === null
          ? "Unknown (origin/main has not been fetched)"
          : c.ahead === 0 && c.behind === 0
            ? "Level with origin/main"
            : `${plural(c.ahead, "commit")} ahead, ${plural(c.behind, "commit")} behind origin/main`,
      ],
    ];
    const warnings = checkoutWarnings(status).filter((w) => w.kind === "sessions");
    put(
      body,
      h(
        "dl",
        { class: "facts" },
        rows.map(([k, v]) => [h("dt", { text: k }), h("dd", {}, v)]),
      ),
      ...warnings.map((w) =>
        banner({
          tone: "warning",
          title: w.title,
          body: "Stop everything, Reset and Restore would break their work; their confirms say so.",
          items: status.sessions.map(describeSession),
          actions: [
            button({
              label: "See them in Processes",
              size: "sm",
              icon: "arrow-right",
              onClick: () => (window.location.hash = "#/processes"),
            }),
          ],
        }),
      ),
    );
  }
  const off = store.on("status", update);
  update();
  return { el, destroy: off };
}
