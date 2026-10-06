// Features: each product feature with live numbers from the running product, links to the web
// app's pages that exist, and "Not built yet" where the product has no route for it.

import { actionButton } from "../actions.js";
import { api } from "../api.js";
import { add, externalLink, formatAgo, formatNumber, h, oneAtATime, put } from "../dom.js";
import { icon } from "../icons.js";
import * as store from "../store.js";
import { badge, banner, button, emptyState, skeleton } from "../ui.js";

export const title = "Features";

const ICONS = [
  [/review/, "checks"],
  [/task/, "list"],
  [/outbox|dead|dlq/, "inbox"],
  [/fan/, "route"],
  [/run/, "activity"],
  [/obligation/, "calendar"],
  [/change/, "bell"],
  [/notif|sink|message/, "message"],
  [/flag/, "flag"],
  [/check/, "shield"],
  [/eval/, "gauge"],
];

const STATE = {
  live: { label: "Live", tone: "success", icon: "check-circle" },
  "not-built": { label: "Not built yet", tone: "neutral", icon: "minus-circle" },
  "not-running": { label: "Not running", tone: "warning", icon: "power" },
  offline: { label: "Not running", tone: "warning", icon: "power" },
  error: { label: "Could not read", tone: "danger", icon: "alert-circle" },
};

function normalize(raw) {
  return (raw?.features ?? raw ?? []).map((f) => ({
    id: String(f.id ?? f.title ?? ""),
    title: String(f.title ?? f.id ?? ""),
    summary: String(f.summary ?? ""),
    state: String(f.state ?? "live").replace(/_/g, "-"),
    numbers: (f.numbers ?? []).map((n) => ({
      label: String(n.label ?? ""),
      value: n.value,
      hint: String(n.hint ?? ""),
      tone: n.tone ? String(n.tone) : "",
    })),
    links: (f.links ?? []).map((l) => ({
      label: String(l.label ?? l.url ?? ""),
      url: String(l.url ?? ""),
      live: l.live !== false,
      note: String(l.note ?? ""),
    })),
    note: String(f.note ?? ""),
    error: String(f.error ?? ""),
  }));
}

export function render(root, { scope }) {
  const refresh = button({
    label: "Read again",
    icon: "refresh",
    size: "sm",
    variant: "secondary",
    onClick: () => load(true),
  });
  const stamp = h("span", { class: "muted stamp" });
  const body = h("div", { class: "feature-grid" }, skeleton("card", 6));
  const notice = h("div", { class: "feature-notice" });
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Features", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "What the product can do today, with live numbers from the running product and its pages in the web app. Everything here only reads.",
        ),
      ),
      h("div", { class: "view-actions" }, stamp, refresh),
    ),
    notice,
    body,
  );

  let lastProduct = store.state.parts.product.state;
  let gone = false;
  scope.add(() => (gone = true));
  // one read at a time; a features event that lands mid-read makes one more read after it
  const load = oneAtATime(async (manual = false) => {
    if (gone) return;
    refresh.disabled = true;
    try {
      const data = await api.features();
      if (data.loading) {
        // the helper reads them in the background and says so with a features event
        stamp.textContent = "Reading…";
        if (!store.cached("features")) put(body, skeleton("card", 6));
        return;
      }
      store.setCache("features", data);
      draw(normalize(data));
      stamp.textContent = data.reading ? "Reading again…" : `Read ${formatAgo(Date.now())}`;
    } catch (error) {
      put(
        body,
        emptyState({
          icon: "alert-circle",
          title: "The features could not be read",
          body: error.title || error.detail || "The app's helper did not answer.",
          actions: [button({ label: "Try again", icon: "refresh", onClick: () => load(true) })],
        }),
      );
    } finally {
      refresh.disabled = false;
      if (manual) refresh.focus();
    }
  });

  function draw(features) {
    const productUp = store.state.parts.product.state === "running";
    put(
      notice,
      productUp
        ? ""
        : banner({
            tone: "info",
            title: "The product is not running",
            body: "Live numbers come from the running product. Start it to see them; what is built and what is not shows either way.",
            actions: [
              scope.use(
                actionButton("product-start", {
                  label: "Start the product",
                  variant: "primary",
                  size: "sm",
                }),
              ),
            ],
          }),
    );
    if (!features.length) {
      put(
        body,
        emptyState({
          icon: "features",
          title: "No features to show",
          body: "The app's helper listed none.",
        }),
      );
      return;
    }
    put(body, ...features.map(featureCard));
  }

  function featureCard(f) {
    const state = STATE[f.state] ?? STATE.live;
    const iconName = ICONS.find(([pattern]) => pattern.test(f.id))?.[1] ?? "features";
    return h(
      "article",
      {
        class: "card feature",
        data: { state: f.state },
        attrs: { "aria-labelledby": `feature-${f.id}` },
      },
      h(
        "div",
        { class: "feature-head" },
        h("span", { class: "feature-icon" }, icon(iconName, { size: 20 })),
        h("h2", { class: "feature-title", text: f.title, attrs: { id: `feature-${f.id}` } }),
        badge(state.label, state.tone, state.icon),
      ),
      f.summary ? h("p", { class: "feature-summary", text: f.summary }) : null,
      f.numbers.length
        ? h(
            "dl",
            { class: "numbers" },
            f.numbers.map((n) =>
              h(
                "div",
                { class: "number", data: { tone: n.tone } },
                h("dt", { text: n.label }),
                h("dd", { class: "number-value", text: formatNumber(n.value) }),
                n.hint ? h("dd", { class: "number-hint", text: n.hint }) : null,
              ),
            ),
          )
        : null,
      f.error
        ? h(
            "p",
            { class: "feature-error" },
            icon("alert-circle", { size: 14 }),
            h("span", { text: f.error }),
          )
        : null,
      f.links.length
        ? h(
            "div",
            { class: "feature-links" },
            f.links.map((l) =>
              l.live && l.url
                ? externalLink(l.url, l.label, { class: "chip-link" })
                : h(
                    "span",
                    { class: "chip-link is-off", attrs: { title: l.note || "Not built yet" } },
                    icon("minus-circle", { size: 14 }),
                    h("span", { text: `${l.label} page: not built yet` }),
                  ),
            ),
          )
        : null,
      f.note ? h("p", { class: "feature-note", text: f.note }) : null,
    );
  }

  const cachedData = store.cached("features");
  if (cachedData) draw(normalize(cachedData));
  load();
  scope.add(store.on("event:features", () => load()));
  scope.add(
    store.on("parts", (parts) => {
      if (
        parts.product.state !== lastProduct &&
        ["running", "stopped"].includes(parts.product.state)
      ) {
        lastProduct = parts.product.state;
        load();
      }
    }),
  );
}
