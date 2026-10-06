// What the action views (Run, Data, Checks) share: sections of action cards, laid out by the
// action ids each view knows, and the helper's other curated actions for that area.

import { actionCard } from "../actions.js";
import { add, h, put } from "../dom.js";
import * as store from "../store.js";
import { emptyState, section, skeleton } from "../ui.js";

/** Which view an action belongs to when no view places it by id, read from its group. */
const VIEW_OF_GROUP = [
  [/check|gate|test|lint|quality|eval/i, "checks"],
  [/data|backup|restore|seed|migrat|database|demo/i, "data"],
  [/pipeline|event|kafka|crawl|topic/i, "pipeline"],
  [/flag/i, "flags"],
  [/process|port/i, "processes"],
  [/log/i, "logs"],
  [/doc|github|help|guide/i, "guide"],
];

export function viewOfAction(action) {
  return VIEW_OF_GROUP.find(([pattern]) => pattern.test(action.group))?.[1] ?? "run";
}

const placements = new Map();

/** Remembers which ids a view lays out itself, so "More" sections do not repeat them. */
export function place(view, ids) {
  placements.set(view, new Set([...(placements.get(view) ?? []), ...ids]));
}

function placedAnywhere(id) {
  for (const ids of placements.values()) if (ids.has(id)) return true;
  return false;
}

/**
 * Renders sections of action cards into root and keeps them in step with the catalog: a
 * section whose actions the helper does not offer is left out.
 */
export function actionSections(root, scope, view, sections, { more = true } = {}) {
  const idsOf = (spec) =>
    typeof spec.actions === "function" ? spec.actions() : (spec.actions ?? []);
  place(view, sections.flatMap(idsOf));
  const holder = h("div", { class: "sections" });
  add(root, holder);
  const cards = [];

  function build() {
    for (const card of cards.splice(0)) card.destroy();
    put(holder);
    if (!store.state.actionsLoaded) {
      add(holder, skeleton("card", 4));
      return;
    }
    let shown = 0;
    for (const spec of sections) {
      const ids = idsOf(spec).filter((id) => store.action(id));
      const extra = spec.extra ? spec.extra(scope) : null;
      if (!ids.length && !extra) continue;
      shown += 1;
      const grid = h("div", { class: spec.rows ? "action-rows" : "action-grid" });
      for (const id of ids) {
        const card = actionCard(id, { variant: spec.rows ? "row" : "card" });
        cards.push(card);
        add(grid, card.el);
      }
      add(
        holder,
        section({
          id: spec.id,
          title: spec.title,
          lead: typeof spec.lead === "function" ? spec.lead() : (spec.lead ?? ""),
          actions: spec.headerActions ? spec.headerActions(scope) : [],
          children: [spec.before ? spec.before(scope) : null, ids.length ? grid : null, extra],
        }),
      );
    }
    if (more) {
      const others = store.state.actions.filter(
        (a) => a.source !== "make" && viewOfAction(a) === view && !placedAnywhere(a.id),
      );
      if (others.length) {
        const grid = h("div", { class: "action-grid" });
        for (const action of others) {
          const card = actionCard(action.id);
          cards.push(card);
          add(grid, card.el);
        }
        add(holder, section({ id: `${view}-more`, title: "More", children: [grid] }));
        shown += 1;
      }
    }
    if (!shown) {
      add(
        holder,
        emptyState({
          icon: "info",
          title: "Nothing to run here yet",
          body: "The app's helper offers no actions for this area. Commands lists everything it offers.",
        }),
      );
    }
  }

  let lastIds = "";
  const off = store.on("actions", () => {
    const ids = store.state.actions.map((a) => a.id).join("|");
    if (ids !== lastIds) {
      lastIds = ids;
      build();
    }
  });
  lastIds = store.state.actions.map((a) => a.id).join("|");
  build();
  scope.add(() => {
    off();
    for (const card of cards) card.destroy();
  });
  return holder;
}

/** Scrolls to a section named in the route (#/run/product) once it exists. */
export function revealSection(root, id) {
  if (!id) return;
  window.requestAnimationFrame(() => {
    const target = root.querySelector(`#${CSS.escape(id)}`);
    if (!target) return;
    target.scrollIntoView({ block: "start" });
    target.classList.add("is-highlighted");
    window.setTimeout(() => target.classList.remove("is-highlighted"), 1600);
  });
}
