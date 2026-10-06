// Run: start and stop each part on its own.

import { availability, runAction, targetUrl } from "../actions.js";
import { add, externalLink, h, put } from "../dom.js";
import { icon } from "../icons.js";
import * as store from "../store.js";
import { rich, statusChip } from "../ui.js";
import { actionSections, place, revealSection } from "./common.js";

export const title = "Run";

const TOOL_LINKS = {
  "temporal-ui": "Temporal UI",
  grafana: "Grafana",
  prometheus: "Prometheus",
  langfuse: "Langfuse",
  unleash: "Unleash",
};

const SECTIONS = [
  {
    id: "everything",
    title: "Everything",
    lead: () =>
      rich(
        "The whole UI-only stack with one button: {Docker}, the databases and queues, the services and the web app.",
      ),
    actions: ["start-everything", "stop-everything"],
  },
  {
    id: "docker",
    title: "Docker",
    lead: () => rich("The small virtual computer that runs the databases and the {queue}."),
    actions: ["docker-start", "docker-stop"],
  },
  {
    id: "infra",
    title: "Databases and queues",
    lead: () =>
      rich("Postgres, Redis, Redpanda and Temporal in Docker. Stopping them keeps the data."),
    actions: ["databases-start", "databases-stop", "dev-ps"],
  },
  {
    id: "services",
    title: "The services",
    lead: () =>
      rich(
        "The ten {services|service} of the {UI-only stack}, each on its own port (8001 to 8010). They need the databases.",
      ),
    actions: ["ui-start", "ui-stop", "ui-restart", "ui-wait"],
  },
  {
    id: "web",
    title: "The web app",
    lead: "The screens at localhost:3000. It needs the services.",
    actions: ["web-start", "web-stop"],
    extra: (scope) => linkRow("web", scope),
  },
  {
    id: "product",
    title: "The full product",
    lead: () =>
      rich(
        "Every service in one app, its {worker} and its own web app at 127.0.0.1:3400. A published rule really becomes obligations and messages here.",
      ),
    actions: ["product-start", "product-stop", "product-wait", "product-role"],
    extra: (scope) => linkRow("product", scope),
  },
  {
    id: "image",
    title: "The product from its image",
    lead: "The same product built into the image a deploy ships, run in containers, as CI runs it. It and the product above share ports, so one runs at a time.",
    actions: ["mvp-image", "product-image", "product-image-down"],
  },
  {
    id: "tools",
    title: "Optional tools",
    lead: "Traces and metrics, the AI gateway in a container, and a flag server. None is needed to use the product.",
    actions: ["dev-observability", "dev-llm", "dev-flags"],
    extra: (scope) => toolLinks(scope),
  },
  {
    id: "workers",
    title: "Workers and relays",
    lead: () =>
      rich(
        "Optional helpers for the UI-only stack: a {worker} runs one service's background jobs, an {outbox relay} passes its events to the queue. The full product already runs all of them, with the crawl off.",
      ),
    actions: [],
    extra: (scope) => workersTable(scope),
  },
];

place(
  "run",
  SECTIONS.flatMap((s) => s.actions).concat([
    // offered when colima stop times out (and in Commands), never as a card here
    "force-stop-docker",
    // the Logs view reads these logs; the actions stay in Commands
    "product-logs",
    "product-image-logs",
    "container-logs",
    "open-logs-folder",
    "open-doc",
    "worker-start",
    "worker-stop",
    "relay-start",
    "relay-stop",
  ]),
);

export function render(root, { scope, params }) {
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Run", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "Start and stop each part on its own. Start everything starts Docker, the databases, the services and the web app, in that order.",
        ),
      ),
    ),
  );
  actionSections(root, scope, "run", SECTIONS);
  revealSection(root, params[0]);
  return { update: (next) => revealSection(root, next[0]) };
}

function linkRow(kind, scope) {
  const holder = h("div", { class: "link-row" });
  const sync = () => {
    const links =
      kind === "web"
        ? [{ label: "Open the web app", target: "web" }]
        : [
            { label: "Open the product", target: "product" },
            { label: "Sign-in page", target: "signin" },
            { label: "Internal tools (/admin)", target: "admin" },
          ];
    put(
      holder,
      ...links.map((link) => {
        const target = targetUrl(link.target);
        return target.up
          ? externalLink(target.url, link.label, { class: "btn btn-secondary btn-sm" })
          : h(
              "span",
              { class: "link-off" },
              icon("external", { size: 14 }),
              h("span", { text: `${link.label}: start it first` }),
            );
      }),
    );
  };
  sync();
  scope.add(store.on("parts", sync));
  return holder;
}

function toolLinks(scope) {
  const holder = h("div", { class: "link-row" });
  const sync = () => {
    const up = (store.state.status?.infra ?? []).filter(
      (c) => TOOL_LINKS[c.service] && c.up && c.ports.length,
    );
    put(
      holder,
      ...up.map((c) =>
        externalLink(`http://localhost:${c.ports[0]}`, TOOL_LINKS[c.service], {
          class: "btn btn-secondary btn-sm",
        }),
      ),
    );
    holder.hidden = up.length === 0;
  };
  sync();
  scope.add(store.on("status", sync));
  return holder;
}

function workersTable(scope) {
  const has = ["worker-start", "worker-stop", "relay-start", "relay-stop"].some((id) =>
    store.action(id),
  );
  if (!has) return null;
  const body = h("tbody");
  const table = h(
    "table",
    { class: "table workers" },
    h("caption", { class: "sr-only", text: "Workers and outbox relays by service" }),
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: "Service", attrs: { scope: "col" } }),
        h("th", { text: "Worker", attrs: { scope: "col" } }),
        h("th", { text: "Outbox relay", attrs: { scope: "col" } }),
      ),
    ),
    body,
  );
  const choicesOf = (id) =>
    new Set(
      (store.action(id)?.params.find((p) => p.name === "service")?.choices ?? []).map(
        (c) => c.value,
      ),
    );

  function cell(kind, service) {
    const startId = `${kind}-start`;
    const stopId = `${kind}-stop`;
    const offered = choicesOf(startId);
    if (offered.size && !offered.has(service))
      return h("td", { class: "muted", text: kind === "worker" ? "No worker" : "No outbox" });
    const bg = (store.state.status?.background ?? []).find(
      (b) => b.kind === kind && b.service === service,
    );
    if (!bg && !offered.size) return h("td", { class: "muted", text: "–" });
    const running = Boolean(bg?.pid);
    const run = store.activeRun();
    const busy = run && [startId, stopId].includes(run.actionId) && run.params?.service === service;
    const id = running ? stopId : startId;
    const can = availability(store.action(id));
    const btn = h(
      "button",
      {
        class: `btn btn-sm ${running ? "btn-danger-outline" : "btn-secondary"}`,
        attrs: {
          type: "button",
          "aria-label": `${running ? "Stop" : "Start"} the ${service} ${kind === "worker" ? "worker" : "outbox relay"}`,
        },
        props: { disabled: !can.enabled || busy },
        on: { click: () => runAction(id, { params: { service } }) },
      },
      icon(running ? "stop" : "play", { size: 14 }),
      h("span", { class: "label", text: running ? "Stop" : "Start" }),
    );
    if (!can.enabled) btn.title = can.reason;
    return h(
      "td",
      {},
      h(
        "span",
        { class: "cell-row" },
        statusChip(running ? "running" : "stopped", running ? `Running, pid ${bg.pid}` : "Stopped"),
        btn,
      ),
    );
  }

  const sync = () => {
    const services = new Set([
      ...choicesOf("worker-start"),
      ...choicesOf("relay-start"),
      ...(store.state.status?.background ?? []).map((b) => b.service),
    ]);
    put(
      body,
      ...[...services]
        .sort()
        .map((service) =>
          h(
            "tr",
            {},
            h("th", { text: service, attrs: { scope: "row" } }),
            cell("worker", service),
            cell("relay", service),
          ),
        ),
    );
  };
  sync();
  const offs = [store.on("status", sync), store.on("runs", sync), store.on("actions", sync)];
  scope.add(() => offs.forEach((off) => off()));
  return h("div", { class: "table-wrap card" }, table);
}
