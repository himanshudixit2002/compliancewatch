// Pipeline and events: the crawl report, the queue's consumer groups and topics (read through
// rpk, at most every 30 seconds), and the pages that show the pipeline at work.

import { api } from "../api.js";
import { add, externalLink, formatAgo, formatNumber, h, plural, put } from "../dom.js";
import { icon } from "../icons.js";
import * as store from "../store.js";
import { badge, banner, button, emptyState, rich, section, skeleton } from "../ui.js";
import { actionSections, place } from "./common.js";

export const title = "Pipeline & events";

const SECTIONS = [
  {
    id: "report",
    title: "The crawl report",
    lead: () =>
      rich(
        "Crawl runs, failures, gaps and detection delays per source, read from the pipeline's store. It only reads; the {crawl} itself stays off.",
      ),
    actions: ["crawl-report"],
  },
];

place("pipeline", ["crawl-report"]);

export function render(root, { scope }) {
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Pipeline & events", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          rich(
            "How events move between the services: each {consumer group} with how far behind it is ({lag}), and each {topic} with its messages. Nothing here changes anything.",
          ),
        ),
      ),
    ),
  );
  add(root, eventsSection(scope));
  actionSections(root, scope, "pipeline", SECTIONS);
  add(root, linksSection(scope));
}

function eventsSection(scope) {
  const status = h("p", { class: "muted stamp", attrs: { "aria-live": "polite" } });
  const readButton = button({
    label: "Read again",
    icon: "refresh",
    size: "sm",
    onClick: () => refresh(true),
  });
  const body = h("div", { class: "events" }, skeleton("row", 6));
  let countdown = 0;
  let timer = 0;
  let readAt = 0;

  function setWait(seconds) {
    window.clearInterval(timer);
    countdown = Math.ceil(seconds);
    const tick = () => {
      if (countdown <= 0) {
        window.clearInterval(timer);
        readButton.disabled = false;
        readButton.querySelector(".label").textContent = "Read again";
        // the first read was turned down (another read had just started): ask once more
        if (!readAt && seconds > 0) refresh(false);
        return;
      }
      readButton.disabled = true;
      readButton.querySelector(".label").textContent = `Read again in ${countdown} s`;
      countdown -= 1;
    };
    tick();
    timer = window.setInterval(tick, 1000);
  }
  scope.add(() => window.clearInterval(timer));

  // GET /api/kafka answers the last read at once; POST /api/kafka/refresh asks rpk again (at
  // most every 30 s) and the result arrives as a kafka event (API.md, section 7).
  function show(data) {
    if (data.taken_at) {
      readAt = data.taken_at;
      draw(data);
      status.textContent = data.reading ? "Reading…" : `Read ${formatAgo(data.taken_at * 1000)}`;
    } else {
      status.textContent = data.reading ? "Reading…" : "Not read yet";
    }
    setWait(Number(data.next_in ?? 0));
  }

  async function load() {
    try {
      const data = await api.kafka();
      show(data);
      return data;
    } catch (error) {
      put(
        body,
        emptyState({
          icon: "alert-circle",
          title: "The queue could not be read",
          body: error.title || error.detail || "The app's helper did not answer.",
        }),
      );
      return null;
    }
  }

  async function refresh(manual) {
    readButton.disabled = true;
    try {
      const answer = await api.kafkaRefresh();
      if (answer.started) status.textContent = "Reading…";
      setWait(Number(answer.next_in ?? 0));
      return answer;
    } catch (error) {
      readButton.disabled = false;
      if (manual) status.textContent = error.title || "The queue could not be read";
      return null;
    }
  }

  function draw(data) {
    const groups = (data.groups ?? []).map((g) => ({
      group: String(g.group ?? g.name ?? ""),
      state: String(g.state ?? ""),
      members: Number(g.members ?? 0),
      lag: Number(g.total_lag ?? g.lag ?? 0),
    }));
    const topics = (data.topics ?? []).map((t) => ({
      name: String(t.name ?? ""),
      partitions: Number(t.partitions ?? 0),
      messages: t.messages === null || t.messages === undefined ? null : Number(t.messages),
      dead: Boolean(t.dead_letters ?? String(t.name ?? "").endsWith(".dlq")),
    }));
    const nodes = [];
    if (data.error) {
      nodes.push(
        banner({
          tone: store.state.parts.infra.state === "running" ? "warning" : "info",
          title:
            store.state.parts.infra.state === "running"
              ? "Part of the queue could not be read"
              : "The queue is not running",
          body:
            store.state.parts.infra.state === "running"
              ? data.error
              : "Start the databases and queues (or everything) to see its groups and topics.",
        }),
      );
    }
    const deadWithMessages = topics.filter((t) => t.dead && t.messages);
    if (deadWithMessages.length) {
      nodes.push(
        banner({
          tone: "danger",
          title: `${plural(deadWithMessages.length, "dead-letter topic")} ${deadWithMessages.length === 1 ? "holds" : "hold"} messages`,
          body: "These events could not be handled and wait for someone to look at them.",
          items: deadWithMessages.map((t) => `${t.name}: ${formatNumber(t.messages)} messages`),
        }),
      );
    }
    const maxLag = Math.max(1, ...groups.map((g) => g.lag));
    nodes.push(
      h(
        "div",
        { class: "events-grid" },
        h(
          "div",
          { class: "card table-wrap" },
          h("h3", { class: "table-title", text: "Consumer groups" }),
          groups.length
            ? h(
                "table",
                { class: "table" },
                h("caption", { class: "sr-only", text: "Consumer groups and their lag" }),
                h(
                  "thead",
                  {},
                  h(
                    "tr",
                    {},
                    ["Group", "State", "Readers", "Behind by"].map((t, i) =>
                      h("th", {
                        class: i >= 2 || (i === 1 && t === "Partitions") ? "num" : "",
                        text: t,
                        attrs: { scope: "col" },
                      }),
                    ),
                  ),
                ),
                h(
                  "tbody",
                  {},
                  groups.map((g) =>
                    h(
                      "tr",
                      { data: { lag: g.lag > 0 ? "some" : "none" } },
                      h("th", { attrs: { scope: "row" } }, h("code", { text: g.group })),
                      h("td", { text: g.state || "–" }),
                      h("td", { class: "num", text: String(g.members) }),
                      h(
                        "td",
                        { class: "lag-cell" },
                        h(
                          "span",
                          { class: "lag" },
                          h(
                            "span",
                            { class: "lag-bar", attrs: { "aria-hidden": "true" } },
                            h("span", {
                              vars: { "--value": `${Math.round((g.lag / maxLag) * 100)}%` },
                            }),
                          ),
                          h("span", {
                            class: "num",
                            text: g.lag ? `${formatNumber(g.lag)} messages` : "Up to date",
                          }),
                        ),
                      ),
                    ),
                  ),
                ),
              )
            : h("p", { class: "muted pad", text: "No consumer groups yet." }),
        ),
        h(
          "div",
          { class: "card table-wrap" },
          h("h3", { class: "table-title", text: "Topics" }),
          topics.length
            ? h(
                "table",
                { class: "table" },
                h("caption", { class: "sr-only", text: "Topics and their messages" }),
                h(
                  "thead",
                  {},
                  h(
                    "tr",
                    {},
                    ["Topic", "Partitions", "Messages"].map((t, i) =>
                      h("th", {
                        class: i >= 2 || (i === 1 && t === "Partitions") ? "num" : "",
                        text: t,
                        attrs: { scope: "col" },
                      }),
                    ),
                  ),
                ),
                h(
                  "tbody",
                  {},
                  topics.map((t) =>
                    h(
                      "tr",
                      { data: { dead: t.dead && t.messages ? "yes" : "" } },
                      h(
                        "th",
                        { attrs: { scope: "row" } },
                        h("code", { text: t.name }),
                        t.dead
                          ? badge(
                              t.messages ? "Dead letters" : "Dead letters, empty",
                              t.messages ? "danger" : "neutral",
                            )
                          : null,
                      ),
                      h("td", { class: "num", text: String(t.partitions) }),
                      h("td", {
                        class: "num",
                        text: t.messages === null ? "–" : formatNumber(t.messages),
                      }),
                    ),
                  ),
                ),
              )
            : h("p", { class: "muted pad", text: "No topics yet." }),
        ),
      ),
    );
    put(body, ...nodes);
  }

  // A visit asks for a new read first when the last one is missing or older than 30 seconds
  // (the answer arrives as a kafka event), then shows the last read meanwhile.
  async function open() {
    const cached = store.cached("kafka");
    if (cached) show(cached);
    const age = cached?.taken_at ? Date.now() / 1000 - cached.taken_at : Infinity;
    if (age > 30 && !cached?.reading) await refresh(false);
    await load();
  }
  open();
  scope.add(store.on("cache:kafka", (data) => data && show(data)));
  return section({
    id: "events",
    title: "Events between the services",
    lead: "Read through rpk in the Redpanda container, at most once every 30 seconds.",
    actions: [status, readButton],
    children: [body],
  });
}

function linksSection(scope) {
  const holder = h("div", { class: "link-grid" });
  const sync = () => {
    const status = store.state.status;
    const links = [];
    const temporal = status?.infra.find((c) => c.service === "temporal-ui");
    links.push({
      label: "Temporal UI",
      text: "Each long job (workflow) and its steps.",
      url: temporal?.up && temporal.ports[0] ? `http://localhost:${temporal.ports[0]}` : "",
      off: "Start the databases and queues first.",
    });
    const product = status?.product;
    const worker = product?.worker;
    const internal = product?.internal;
    links.push({
      label: "The worker's loops",
      text: "What the product's worker runs: relays, consumers, sweeps and task queues.",
      url: worker?.up ? `${worker.url || `http://127.0.0.1:${worker.port}`}/loops` : "",
      off: "Start the product first.",
    });
    links.push({
      label: "Sources (JSON)",
      text: "The pipeline's sources and how each stands.",
      url: internal?.up
        ? `${internal.url || `http://127.0.0.1:${internal.port}`}/v1/pipeline/sources`
        : "",
      off: "Start the product first.",
    });
    links.push({
      label: "Open tasks (JSON)",
      text: "The pipeline's tasks waiting for a person.",
      url: internal?.up
        ? `${internal.url || `http://127.0.0.1:${internal.port}`}/v1/pipeline/tasks?status=open`
        : "",
      off: "Start the product first.",
    });
    put(
      holder,
      ...links.map((link) =>
        h(
          "div",
          { class: "link-card" },
          h(
            "p",
            { class: "link-card-title" },
            icon("external", { size: 14 }),
            h("span", { text: link.label }),
          ),
          h("p", { class: "link-card-text", text: link.text }),
          link.url
            ? externalLink(link.url, "Open", {
                class: "btn btn-secondary btn-sm",
                ariaLabel: `Open ${link.label} (opens in your browser)`,
              })
            : h("p", { class: "link-off", text: link.off }),
        ),
      ),
    );
  };
  sync();
  scope.add(store.on("status", sync));
  return section({
    id: "open",
    title: "See it at work",
    lead: "Pages that show the pipeline and the events. The JSON pages are the product's own answers.",
    children: [holder],
  });
}
