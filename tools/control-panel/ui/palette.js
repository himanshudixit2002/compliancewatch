// The command palette (⌘K): find any action, any place in the app and any Guide entry by typing.

import { actionIcon, availability, openUrl, runAction, targetUrl } from "./actions.js";
import { add, cx, h, put, reducedMotion, uid } from "./dom.js";
import { GLOSSARY, RECIPES, TROUBLE } from "./guide.js";
import { icon } from "./icons.js";
import { SAFETY } from "./model.js";
import * as store from "./store.js";
import { badge } from "./ui.js";

let open = false;

export const PLACES = [
  ["home", "Home", "home"],
  ["run", "Run", "play"],
  ["data", "Data", "database"],
  ["checks", "Checks", "checks"],
  ["features", "Features", "features"],
  ["pipeline", "Pipeline & events", "pipeline"],
  ["flags", "Flags", "flag"],
  ["processes", "Processes", "cpu"],
  ["logs", "Logs", "logs"],
  ["commands", "Commands", "terminal"],
  ["guide", "Guide", "book"],
];

function entries() {
  const items = [];
  for (const action of store.state.actions) {
    const can = availability(action);
    const target = action.source === "make" ? `make ${action.id.replace(/^make:/, "")}` : "";
    const same = action.coveredBy ? store.action(action.coveredBy) : null;
    // a make target that a curated action covers is found by its own name, not by the curated
    // action's words, so "start the databases" does not list it twice
    items.push({
      kind: "Actions",
      id: `action:${action.id}`,
      title: same ? target : action.title,
      text: [
        target && !same ? target : "",
        !can.enabled ? can.reason : same ? `Same as “${same.title}”` : action.summary,
      ]
        .filter(Boolean)
        .join(" · "),
      hay: (same
        ? [target, action.id, action.keywords]
        : [action.title, action.summary, action.id, action.group, action.keywords, action.command]
      ).join(" "),
      icon: actionIcon(action),
      safety: action.safety,
      disabled: !can.enabled,
      weight: same ? 0.6 : action.source === "make" ? 0.8 : 1.2,
      run: () => runAction(action.id),
    });
  }
  for (const [id, title, iconName] of PLACES) {
    items.push({
      kind: "Go to",
      id: `view:${id}`,
      title,
      text: "",
      hay: title,
      icon: iconName,
      weight: 1.1,
      run: () => (window.location.hash = `#/${id}`),
    });
  }
  for (const [target, title] of [
    ["web", "Open the web app"],
    ["signin", "Open the product's sign-in page"],
  ]) {
    const t = targetUrl(target);
    items.push({
      kind: "Go to",
      id: `open:${target}`,
      title,
      text: t.up ? t.url : target === "web" ? "Start everything first" : "Start the product first",
      hay: `${title} open browser`,
      icon: "external",
      disabled: !t.up,
      weight: 1.1,
      run: () => openUrl(t.url),
    });
  }
  for (const recipe of RECIPES) {
    items.push({
      kind: "Guide",
      id: `recipe:${recipe.id}`,
      title: recipe.title,
      text: "Recipe, step by step",
      hay: `${recipe.title} ${recipe.intro} recipe how`,
      icon: recipe.icon,
      weight: 1,
      run: () => (window.location.hash = `#/guide/recipes/recipe-${recipe.id}`),
    });
  }
  TROUBLE.forEach((t, index) =>
    items.push({
      kind: "Guide",
      id: `trouble:${index}`,
      title: t.title,
      text: "When something goes wrong",
      hay: `${t.title} ${t.why} ${t.fix} problem error help`,
      icon: "warning",
      weight: 0.9,
      run: () => (window.location.hash = `#/guide/trouble/trouble-${index}`),
    }),
  );
  for (const g of GLOSSARY) {
    items.push({
      kind: "Guide",
      id: `term:${g.id}`,
      title: `${g.term}: what it means`,
      text: g.text,
      hay: `${g.term} ${g.text} glossary meaning`,
      icon: "book",
      weight: 0.7,
      run: () => (window.location.hash = `#/guide/glossary/${g.id}`),
    });
  }
  items.push({
    kind: "Guide",
    id: "tour",
    title: "Take the tour",
    text: "Five short steps around this window",
    hay: "tour help start introduction",
    icon: "sparkles",
    weight: 1,
    run: () => window.dispatchEvent(new CustomEvent("cw:tour")),
  });
  return items;
}

const SUGGESTED = [
  "action:start-everything",
  "action:stop-everything",
  "open:web",
  "action:load-demo-data",
  "action:gate:check",
  "view:guide",
];

function score(item, words) {
  const title = item.title.toLowerCase();
  const hay = item.hay.toLowerCase();
  let total = 0;
  for (const word of words) {
    if (title.startsWith(word)) total += 4;
    else if (title.includes(` ${word}`)) total += 3;
    else if (title.includes(word)) total += 2;
    else if (hay.includes(word)) total += 0.6;
    else return 0;
  }
  return total * item.weight - (item.disabled ? 0.5 : 0);
}

export function openPalette(prefill = "") {
  if (open) return;
  open = true;
  const listId = uid("palette-list");
  const all = entries();
  let results = [];
  let active = 0;
  const input = h("input", {
    class: "palette-input",
    attrs: {
      type: "text",
      role: "combobox",
      "aria-expanded": "true",
      "aria-controls": listId,
      "aria-autocomplete": "list",
      "aria-label": "Search actions, places and the Guide",
      placeholder: "What do you want to do?",
      autocomplete: "off",
      spellcheck: "false",
    },
    props: { value: prefill },
  });
  const list = h("ul", {
    class: "palette-list",
    attrs: { id: listId, role: "listbox", "aria-label": "Results" },
  });
  const hint = h(
    "p",
    { class: "palette-hint" },
    h("span", {}, h("kbd", { text: "↑" }), h("kbd", { text: "↓" }), " to move"),
    h("span", {}, h("kbd", { text: "↵" }), " to run or open"),
    h("span", {}, h("kbd", { text: "esc" }), " to close"),
  );
  const dialog = h(
    "dialog",
    { class: "palette", attrs: { "aria-label": "Search actions, places and the Guide" } },
    h("div", { class: "palette-search" }, icon("search", { size: 20 }), input),
    list,
    hint,
  );

  /** Closes the palette, then (once focus is back where it was) runs what was chosen. */
  function close(then) {
    if (!open) return;
    open = false;
    dialog.classList.add("closing");
    window.setTimeout(
      () => {
        if (dialog.open) dialog.close();
        dialog.remove();
        then?.();
      },
      reducedMotion() ? 0 : 100,
    );
  }

  function choose(item) {
    if (!item) return;
    close(() => item.run());
  }

  function search() {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) {
      results = SUGGESTED.map((id) => all.find((item) => item.id === id)).filter(Boolean);
    } else {
      const scored = all
        .map((item) => ({ item, value: score(item, words) }))
        .filter((r) => r.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, 40);
      // one section per kind, the section with the best match first
      const best = new Map();
      for (const r of scored) if (!best.has(r.item.kind)) best.set(r.item.kind, r.value);
      results = scored
        .sort((a, b) => best.get(b.item.kind) - best.get(a.item.kind) || b.value - a.value)
        .map((r) => r.item);
    }
    active = 0;
    draw();
  }

  function draw() {
    put(list);
    if (!results.length) {
      add(
        list,
        h("li", {
          class: "palette-empty",
          attrs: { role: "presentation" },
          text: "Nothing matches. Try other words, like start, backup or check.",
        }),
      );
      input.removeAttribute("aria-activedescendant");
      return;
    }
    let lastKind = "";
    results.forEach((item, index) => {
      if (item.kind !== lastKind && input.value.trim()) {
        add(
          list,
          h("li", { class: "palette-group", text: item.kind, attrs: { role: "presentation" } }),
        );
        lastKind = item.kind;
      }
      const optionId = `${listId}-${index}`;
      add(
        list,
        h(
          "li",
          {
            class: cx("palette-item", { active: index === active, disabled: item.disabled }),
            attrs: {
              id: optionId,
              role: "option",
              "aria-selected": String(index === active),
              "aria-disabled": item.disabled ? "true" : null,
            },
            on: {
              mousemove: () => {
                if (active !== index) {
                  active = index;
                  highlight();
                }
              },
              click: () => choose(item),
            },
          },
          h("span", { class: "palette-icon" }, icon(item.icon, { size: 18 })),
          h(
            "span",
            { class: "palette-text" },
            h("span", { class: "palette-title", text: item.title }),
            item.text ? h("span", { class: "palette-sub", text: item.text }) : null,
          ),
          item.safety && item.safety !== "safe"
            ? badge(SAFETY[item.safety].label, SAFETY[item.safety].tone)
            : null,
        ),
      );
    });
    highlight();
  }

  function highlight() {
    const options = [...list.querySelectorAll("[role='option']")];
    options.forEach((el, index) => {
      el.classList.toggle("active", index === active);
      el.setAttribute("aria-selected", String(index === active));
    });
    const current = options[active];
    if (current) {
      input.setAttribute("aria-activedescendant", current.id);
      current.scrollIntoView({ block: "nearest" });
    }
  }

  input.addEventListener("input", search);
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      active = Math.min(results.length - 1, active + 1);
      highlight();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      active = Math.max(0, active - 1);
      highlight();
    } else if (event.key === "Home" && event.metaKey) {
      active = 0;
      highlight();
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(results[active]);
    }
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  add(document.body, dialog);
  dialog.showModal();
  input.focus();
  search();
}

export function isPaletteOpen() {
  return open;
}
