// Commands: every action the helper offers, searchable and grouped, the Makefile's documented
// targets among them. One that cannot run says why.

import { actionCard } from "../actions.js";
import { add, h, plural, put, sentence } from "../dom.js";
import { SAFETY } from "../model.js";
import * as store from "../store.js";
import { emptyState, skeleton } from "../ui.js";
import { revealSection } from "./common.js";

export const title = "Commands";

export function matchAction(action, words) {
  if (!words.length) return true;
  const hay = [
    action.title,
    action.summary,
    action.id,
    action.group,
    action.command,
    action.keywords,
    ...action.whatHappens,
  ]
    .join(" ")
    .toLowerCase();
  return words.every((word) => hay.includes(word));
}

export function render(root, { scope, params = [] }) {
  let query = "";
  let safety = "all";
  let showMake = true;
  const cards = new Map();
  const search = h("input", {
    class: "input search-input",
    attrs: {
      type: "search",
      placeholder: "Search every action",
      "aria-label": "Search every action",
      autocomplete: "off",
    },
    on: {
      input: (e) => {
        query = e.target.value.trim().toLowerCase();
        apply();
      },
    },
  });
  const chipDefs = [
    ["all", "All"],
    ...Object.entries(SAFETY).map(([key, meta]) => [key, meta.label]),
  ];
  const chips = h(
    "div",
    { class: "chips", attrs: { role: "group", "aria-label": "Safety" } },
    chipDefs.map(([key, label]) =>
      h("button", {
        class: "chip",
        text: label,
        data: { filter: key, tone: SAFETY[key]?.tone ?? "" },
        attrs: { type: "button", "aria-pressed": String(key === safety) },
        on: {
          click: () => {
            safety = key;
            for (const chip of chips.children)
              chip.setAttribute("aria-pressed", String(chip.dataset.filter === key));
            apply();
          },
        },
      }),
    ),
  );
  const makeToggle = h("input", {
    attrs: { type: "checkbox", id: "show-make" },
    props: { checked: showMake },
    on: {
      change: (e) => {
        showMake = e.target.checked;
        apply();
      },
    },
  });
  const count = h("p", { class: "muted count", attrs: { "aria-live": "polite" } });
  const list = h("div", { class: "command-groups" }, skeleton("row", 8));
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Commands", attrs: { tabindex: "-1" } }),
        h(
          "p",
          { class: "view-lead" },
          "Every action this app can run, the project's documented make targets among them. Each says what it does and how safe it is; one that cannot run now says why. A make target that an action here already does is found by searching for it.",
        ),
      ),
    ),
    h(
      "div",
      { class: "toolbar sticky-toolbar" },
      search,
      chips,
      h(
        "label",
        { class: "check-field", attrs: { for: "show-make" } },
        makeToggle,
        h("span", { text: "Include make targets" }),
      ),
      count,
    ),
    list,
  );

  function groupTitle(id) {
    const group = store.state.groups.find((g) => g.id === id);
    return group?.title || sentence(id || "Other");
  }

  function build() {
    for (const card of cards.values()) card.destroy();
    cards.clear();
    if (!store.state.actionsLoaded) return;
    const order = [...store.state.groups.map((g) => g.id)];
    for (const action of store.state.actions)
      if (!order.includes(action.group)) order.push(action.group);
    const sections = [];
    for (const groupId of order) {
      const actions = store.state.actions.filter((a) => a.group === groupId);
      if (!actions.length) continue;
      const grid = h("div", { class: "action-rows" });
      for (const action of actions) {
        const card = actionCard(action.id, { variant: "row" });
        cards.set(action.id, card);
        add(grid, card.el);
      }
      const headingId = `group-${groupId || "other"}`.replace(/[^a-z0-9-]/gi, "-");
      sections.push(
        h(
          "section",
          {
            class: "command-group",
            data: { group: groupId },
            attrs: { "aria-labelledby": headingId },
          },
          h("h2", { class: "section-title", text: groupTitle(groupId), attrs: { id: headingId } }),
          grid,
        ),
      );
    }
    put(
      list,
      ...sections,
      h(
        "div",
        { class: "no-match", attrs: { hidden: true } },
        emptyState({
          icon: "search",
          title: "No action matches",
          body: "Try other words, or press ⌘K to search everything, the Guide too.",
        }),
      ),
    );
    apply();
    if (pending) reveal(pending);
  }

  // a make target that a curated action covers (make dev-down: Stop the databases) stays out of
  // the list, under the same title, and shows when someone searches for it
  const listed = (action) => !(action.source === "make" && action.coveredBy);

  function apply() {
    const words = query.split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const action of store.state.actions) {
      const card = cards.get(action.id);
      if (!card) continue;
      const visible =
        matchAction(action, words) &&
        (safety === "all" || action.safety === safety) &&
        (showMake || action.source !== "make") &&
        (words.length > 0 || listed(action));
      card.el.hidden = !visible;
      if (visible) shown += 1;
    }
    for (const group of list.querySelectorAll(".command-group")) {
      group.hidden = ![...group.querySelectorAll(".action-card")].some((el) => !el.hidden);
    }
    const none = list.querySelector(".no-match");
    if (none) none.hidden = shown > 0;
    count.textContent =
      words.length || safety !== "all"
        ? `${plural(shown, "action")} ${shown === 1 ? "matches" : "match"}`
        : plural(shown, "action");
  }

  /** Shows one action's card (#/commands/<id>): every filter off, the card scrolled to. */
  let pending = "";
  function reveal(id) {
    if (!cards.has(id)) {
      pending = id;
      return;
    }
    pending = "";
    query = "";
    search.value = "";
    safety = "all";
    for (const chip of chips.children)
      chip.setAttribute("aria-pressed", String(chip.dataset.filter === "all"));
    apply();
    revealSection(root, `action-${id}`);
    window.requestAnimationFrame(() =>
      root
        .querySelector(`#${CSS.escape(`action-${id}`)} [data-role='run']`)
        ?.focus({ preventScroll: true }),
    );
  }

  let lastIds = "";
  scope.add(
    store.on("actions", () => {
      const ids = store.state.actions.map((a) => a.id).join("|");
      if (ids !== lastIds) {
        lastIds = ids;
        build();
      }
    }),
  );
  lastIds = store.state.actions.map((a) => a.id).join("|");
  build();
  reveal(decodeURIComponent(params[0] ?? ""));
  scope.add(() => {
    for (const card of cards.values()) card.destroy();
  });
  return { update: (next) => reveal(decodeURIComponent(next[0] ?? "")) };
}
