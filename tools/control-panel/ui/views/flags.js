// Flags: every switch in packages/flags/registry.json, in plain words, with the value this Mac
// gives it. Read only: the app never changes a flag.

import { actionButton } from "../actions.js";
import { api } from "../api.js";
import { add, cx, h, plural, put, uid } from "../dom.js";
import { PLAIN_FLAGS } from "../guide.js";
import { icon } from "../icons.js";
import * as store from "../store.js";
import { badge, banner, button, emptyState, rich, skeleton } from "../ui.js";

export const title = "Flags";

function normalize(raw) {
  return (raw?.flags ?? raw ?? []).map((f) => {
    const type = String(f.type ?? "");
    const value = f.value === null || f.value === undefined ? null : String(f.value);
    const def = String(f.default ?? "");
    const effective = value ?? def;
    return {
      name: String(f.name ?? ""),
      type,
      owner: String(f.owner ?? ""),
      default: def,
      env: String(f.env ?? ""),
      value,
      source: String(f.source ?? ""),
      description: String(f.description ?? ""),
      removal: String(f.removal ?? ""),
      expires: String(f.expires ?? ""),
      effective,
      changed: value !== null && value !== def,
      on: type === "bool" ? ["true", "1", "yes", "on"].includes(effective.toLowerCase()) : null,
    };
  });
}

const FILTERS = [
  ["all", "All"],
  ["on", "On"],
  ["changed", "Set on this Mac"],
];

export function render(root, { scope }) {
  let flags = [];
  let filter = "all";
  let query = "";
  const search = h("input", {
    class: "input search-input",
    attrs: {
      type: "search",
      placeholder: "Search flags",
      "aria-label": "Search flags",
      autocomplete: "off",
    },
    on: {
      input: (e) => {
        query = e.target.value.trim().toLowerCase();
        draw();
      },
    },
  });
  const chips = h(
    "div",
    { class: "chips", attrs: { role: "group", "aria-label": "Show" } },
    FILTERS.map(([key, label]) =>
      h("button", {
        class: "chip",
        text: label,
        attrs: { type: "button", "aria-pressed": String(key === filter) },
        data: { filter: key },
        on: {
          click: () => {
            filter = key;
            for (const chip of chips.children)
              chip.setAttribute("aria-pressed", String(chip.dataset.filter === key));
            draw();
          },
        },
      }),
    ),
  );
  const count = h("p", { class: "muted count", attrs: { "aria-live": "polite" } });
  const body = h("div", { class: "card table-wrap flags-wrap" }, skeleton("row", 8));
  const error = h("div");
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Flags", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          rich(
            "The switches that turn features on and off, in plain words, with the value this Mac gives each one. This app only shows them: a {flag} changes in .env, and what reads it needs a restart.",
          ),
        ),
      ),
      h(
        "div",
        { class: "view-actions" },
        scope.use(actionButton("open-env", { label: "Open .env", iconName: "file", size: "sm" })),
        scope.use(
          actionButton("flags-check", {
            label: "Check the registry",
            iconName: "checks",
            size: "sm",
          }),
        ),
      ),
    ),
    h("div", { class: "toolbar" }, search, chips, count),
    error,
    body,
  );

  function matches(f) {
    if (filter === "on" && !(f.on === true || (f.on === null && f.effective))) return false;
    if (filter === "changed" && f.value === null) return false;
    if (!query) return true;
    return [f.name, f.env, f.owner, f.description, PLAIN_FLAGS[f.name] ?? ""]
      .join(" ")
      .toLowerCase()
      .includes(query);
  }

  function valueBadge(f) {
    if (f.on === true) return badge("On", "success", "check-circle");
    if (f.on === false) return badge("Off", "neutral", "minus-circle");
    return badge(f.effective || "(empty)", "info");
  }

  function draw() {
    const shown = flags.filter(matches);
    count.textContent = `${plural(shown.length, "flag")} of ${flags.length}`;
    if (!flags.length) {
      put(body, emptyState({ icon: "flag", title: "No flags to show" }));
      return;
    }
    if (!shown.length) {
      put(
        body,
        emptyState({
          icon: "search",
          title: "No flag matches",
          body: "Try another word, or show all flags.",
        }),
      );
      return;
    }
    const rows = [];
    for (const f of shown) {
      const detailId = uid("flag");
      const toggle = h(
        "button",
        {
          class: "row-toggle",
          attrs: { type: "button", "aria-expanded": "false", "aria-controls": detailId },
          on: {
            click: () => {
              const open = toggle.getAttribute("aria-expanded") !== "true";
              toggle.setAttribute("aria-expanded", String(open));
              detail.hidden = !open;
            },
          },
        },
        icon("chevron-right", { size: 14 }),
        h("span", { class: "flag-name", text: f.name }),
      );
      const detail = h(
        "tr",
        { class: "flag-detail", attrs: { id: detailId, hidden: true } },
        h(
          "td",
          { attrs: { colspan: "4" } },
          h(
            "dl",
            { class: "facts" },
            h("dt", { text: "What it does" }),
            h("dd", { text: f.description || "No description in the registry." }),
            h("dt", { text: "Set with" }),
            h("dd", {}, h("code", { text: f.env || "–" })),
            h("dt", { text: "Default" }),
            h("dd", {}, h("code", { text: f.default || "(empty)" })),
            h("dt", { text: "This Mac" }),
            h("dd", {
              text:
                f.value === null
                  ? "Not set, so the default applies"
                  : `${f.value} (set in ${f.source || ".env"})`,
            }),
            h("dt", { text: "Owner" }),
            h("dd", { text: f.owner || "–" }),
            h("dt", { text: "Goes away" }),
            h("dd", {
              text:
                [f.removal, f.expires ? `Expires ${f.expires}.` : ""].filter(Boolean).join(" ") ||
                "–",
            }),
          ),
        ),
      );
      rows.push(
        h(
          "tr",
          { class: cx("flag-row", { changed: f.changed }) },
          h("th", { attrs: { scope: "row" } }, toggle),
          h("td", {
            class: "flag-plain",
            text: PLAIN_FLAGS[f.name] ?? f.description.split(". ")[0],
          }),
          h(
            "td",
            {},
            valueBadge(f),
            f.changed
              ? h("span", { class: "flag-set", text: `set in ${f.source || ".env"}` })
              : null,
          ),
          h("td", { class: "muted", text: f.owner }),
        ),
        detail,
      );
    }
    put(
      body,
      h(
        "table",
        { class: "table flags" },
        h("caption", { class: "sr-only", text: "Flags, what each does and its value on this Mac" }),
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            ["Flag", "What it does", "On this Mac", "Owner"].map((t) =>
              h("th", { text: t, attrs: { scope: "col" } }),
            ),
          ),
        ),
        h("tbody", {}, rows),
      ),
    );
  }

  async function load() {
    try {
      const data = await api.flags();
      store.setCache("flags", data);
      flags = normalize(data);
      put(
        error,
        data.error
          ? banner({
              tone: "warning",
              title: "The flag registry could not be read",
              body: data.error,
            })
          : "",
      );
      draw();
    } catch (e) {
      put(
        body,
        emptyState({
          icon: "alert-circle",
          title: "The flags could not be read",
          body: e.title || e.detail || "The app's helper did not answer.",
          actions: [button({ label: "Try again", icon: "refresh", onClick: load })],
        }),
      );
    }
  }

  const cachedData = store.cached("flags");
  if (cachedData) {
    flags = normalize(cachedData);
    draw();
  }
  load();
}
