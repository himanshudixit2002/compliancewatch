// The Guide: how ComplianceWatch works, what each part does, recipes whose steps run right here,
// the glossary, what to do when something goes wrong, and what this app will never do.

import { actionButton, openUrl, showRequestError, targetUrl } from "../actions.js";
import { api } from "../api.js";
import { add, externalLink, h, oneAtATime, put } from "../dom.js";
import {
  APP_PARTS,
  DATA_NOTE,
  DOCS_FALLBACK,
  FLOW,
  GLOSSARY,
  GUIDE_SECTIONS,
  HELPERS,
  INFRA_PARTS,
  NEVER,
  ON_THIS_MAC,
  PRODUCT_LINE,
  RECIPES,
  SERVICE_PARTS,
  TROUBLE,
  WAYS,
} from "../guide.js";
import { icon } from "../icons.js";
import * as store from "../store.js";
import { badge, banner, button, copyButton, statusChip, toast } from "../ui.js";

export const title = "Guide";

let startTour = () => {};
export function onStartTour(fn) {
  startTour = fn;
}

export function render(root, { scope, params }) {
  let current = GUIDE_SECTIONS.some((s) => s.id === params[0]) ? params[0] : "how";
  const content = h("div", { class: "guide-content" });
  const nav = h(
    "nav",
    { class: "guide-nav", attrs: { "aria-label": "Guide" } },
    h(
      "ul",
      { attrs: { role: "list" } },
      GUIDE_SECTIONS.map((s) =>
        h(
          "li",
          {},
          h(
            "a",
            {
              class: "guide-link",
              attrs: { href: `#/guide/${s.id}`, "aria-current": s.id === current ? "page" : null },
              data: { section: s.id },
            },
            icon(s.icon, { size: 16 }),
            h("span", { text: s.nav ?? s.title }),
          ),
        ),
      ),
    ),
    button({
      label: "Take the tour",
      icon: "sparkles",
      variant: "secondary",
      size: "sm",
      className: "tour-replay",
      onClick: () => startTour(),
    }),
  );
  add(
    root,
    h(
      "header",
      { class: "view-header" },
      h(
        "div",
        { class: "view-heading" },
        h("h1", { class: "view-title", text: "Guide", attrs: { tabindex: "-1" } }),
        h("p", {
          class: "view-lead",
          text: "How ComplianceWatch works and how to do things with this app, in plain words, with a button for each step this app can do for you.",
        }),
      ),
    ),
    h("div", { class: "guide-layout" }, nav, content),
  );

  let sectionScope = [];
  function show(id, anchor) {
    for (const fn of sectionScope.splice(0)) fn();
    current = id;
    for (const link of nav.querySelectorAll(".guide-link")) {
      if (link.dataset.section === id) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    const local = { add: (fn) => sectionScope.push(fn), use: (c) => use(c, sectionScope) };
    const builders = { how, parts, recipes, glossary, trouble, never, more };
    put(content, builders[id](local));
    if (anchor) {
      window.requestAnimationFrame(() => {
        const target = content.querySelector(`#${CSS.escape(anchor)}`);
        if (target) {
          target.scrollIntoView({ block: "center" });
          target.classList.add("is-highlighted");
          target.setAttribute("tabindex", "-1");
          target.focus({ preventScroll: true });
          window.setTimeout(() => target.classList.remove("is-highlighted"), 1800);
        }
      });
    } else {
      content.scrollTop = 0;
    }
  }
  scope.add(() => sectionScope.forEach((fn) => fn()));
  show(current, params[1]);
  return {
    update(next) {
      const id = GUIDE_SECTIONS.some((s) => s.id === next[0]) ? next[0] : "how";
      if (id !== current || next[1]) {
        show(id, next[1]);
        if (!next[1]) content.querySelector("h2")?.focus?.();
      }
    },
  };
}

function use(component, list) {
  if (component?.el) {
    list.push(() => component.destroy?.());
    return component.el;
  }
  if (component?._destroy) list.push(component._destroy);
  return component;
}

function heading(text, id) {
  return h("h2", { class: "guide-title", text, attrs: { id, tabindex: "-1" } });
}

// ---- how it works -------------------------------------------------------------------------------

function how(scope) {
  return h(
    "div",
    { class: "guide-section" },
    heading("How ComplianceWatch works", "how-title"),
    h("p", { class: "guide-lead", text: PRODUCT_LINE }),
    h(
      "figure",
      { class: "flow-figure" },
      h(
        "ol",
        {
          class: "flow",
          attrs: { "aria-label": "From a regulator's notice to the business owner" },
        },
        FLOW.map((step, index) =>
          h(
            "li",
            { class: "flow-step" },
            h("span", { class: "flow-icon" }, icon(step.icon, { size: 20 })),
            h("span", {
              class: "flow-num",
              text: String(index + 1),
              attrs: { "aria-hidden": "true" },
            }),
            h("span", { class: "flow-title", text: step.title }),
            h("span", { class: "flow-text", text: step.text }),
          ),
        ),
      ),
      h(
        "figcaption",
        { class: "helpers" },
        h("span", { class: "helpers-label", text: "Helping along the way" }),
        h(
          "ul",
          { class: "helper-list", attrs: { role: "list" } },
          HELPERS.map((helper) =>
            h(
              "li",
              {},
              h("strong", { text: helper.title }),
              h("span", { text: ` ${helper.text}` }),
            ),
          ),
        ),
      ),
    ),
    h(
      "div",
      { class: "guide-card card" },
      h("h3", { class: "guide-sub", text: "On this Mac" }),
      h(
        "ul",
        { class: "check-list", attrs: { role: "list" } },
        ON_THIS_MAC.map((line) =>
          h("li", {}, icon("shield", { size: 16 }), h("span", { text: line })),
        ),
      ),
    ),
    h("h3", { class: "guide-sub", text: "Two ways to run it" }),
    h("div", { class: "ways" }, waysCards(scope)),
    h("h3", { class: "guide-sub", text: "Where your data lives" }),
    h("p", { text: DATA_NOTE }),
  );
}

function waysCards(scope) {
  return WAYS.map((way) =>
    h(
      "article",
      { class: "card way" },
      h("p", { class: "way-title" }, icon(way.icon, { size: 18 }), h("span", { text: way.title })),
      h("p", { class: "way-text", text: way.text }),
      scope.use(actionButton(way.action, { label: way.label, variant: "primary", size: "sm" })),
    ),
  );
}

// ---- the parts ----------------------------------------------------------------------------------

function parts(scope) {
  const infra = h("div", { class: "part-grid" });
  const services = h("tbody");
  const apps = h("div", { class: "part-grid" });
  const draw = () => {
    const status = store.state.status;
    const p = store.state.parts;
    put(
      infra,
      ...INFRA_PARTS.map((part) => {
        let state = "unknown";
        let label = "Checking";
        if (part.id === "docker") {
          state = p.docker.state;
          label = p.docker.label;
        } else {
          const items = p.infra.items ?? [];
          const item = items.find(
            (i) => i.name === part.id || (part.id === "temporal" && i.name === "temporal"),
          );
          if (item) {
            state = item.state;
            label =
              {
                running: "Running",
                stopped: "Stopped",
                problem: "Needs attention",
                busy: "Starting",
              }[item.state] ?? "Stopped";
          }
        }
        return partCard(part, state, label);
      }),
    );
    put(
      services,
      ...SERVICE_PARTS.map((svc) => {
        const live = status?.services.find((s) => s.name === svc.name);
        const state = live?.up ? "running" : live?.up === false ? "stopped" : "unknown";
        return h(
          "tr",
          {},
          h("th", { attrs: { scope: "row" } }, h("code", { text: svc.name })),
          h("td", { class: "num", text: String(live?.port ?? svc.port) }),
          h("td", { text: svc.text }),
          h(
            "td",
            {},
            statusChip(
              state,
              state === "running" ? "Answering" : state === "stopped" ? "Stopped" : "Checking",
            ),
          ),
        );
      }),
    );
    put(
      apps,
      ...APP_PARTS.map((part) => {
        const live = part.id === "web" ? p.web : part.id === "product" ? p.product : null;
        return partCard(part, live?.state ?? "", live?.label ?? "");
      }),
    );
  };
  draw();
  scope.add(store.on("parts", draw));
  return h(
    "div",
    { class: "guide-section" },
    heading("What each part does", "parts-title"),
    h("p", {
      class: "guide-lead",
      text: "ComplianceWatch is made of small parts that talk to each other. The lights show which run right now.",
    }),
    h("h3", { class: "guide-sub", text: "Underneath: Docker and the databases" }),
    infra,
    h("h3", { class: "guide-sub", text: "The ten services" }),
    h(
      "div",
      { class: "card table-wrap" },
      h(
        "table",
        { class: "table" },
        h("caption", {
          class: "sr-only",
          text: "The ten services, their ports and what each does",
        }),
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            ["Service", "Port", "What it does", "Now"].map((t) =>
              h("th", { text: t, attrs: { scope: "col" } }),
            ),
          ),
        ),
        services,
      ),
    ),
    h("h3", { class: "guide-sub", text: "On top: the apps" }),
    apps,
  );
}

function partCard(part, state, label) {
  return h(
    "article",
    { class: "card part", attrs: { id: `part-${part.id}` } },
    h(
      "div",
      { class: "part-head" },
      h("span", { class: "part-icon" }, icon(part.icon, { size: 18 })),
      h("h4", { class: "part-title", text: part.title }),
      state ? statusChip(state, label) : null,
    ),
    h("p", { class: "part-text", text: part.text }),
    part.where
      ? h("p", { class: "part-where" }, icon("link", { size: 12 }), h("span", { text: part.where }))
      : null,
  );
}

// ---- recipes ------------------------------------------------------------------------------------

function recipes(scope) {
  const index = h(
    "ul",
    { class: "recipe-index", attrs: { role: "list", "aria-label": "Recipes" } },
    RECIPES.map((r) =>
      h(
        "li",
        {},
        h(
          "a",
          { class: "chip-link", attrs: { href: `#/guide/recipes/recipe-${r.id}` } },
          icon(r.icon, { size: 14 }),
          h("span", { text: r.title }),
        ),
      ),
    ),
  );
  return h(
    "div",
    { class: "guide-section" },
    heading("Step-by-step recipes", "recipes-title"),
    h("p", {
      class: "guide-lead",
      text: "Common tasks, one step at a time. A step this app can do has a button here, and a tick when it is already done.",
    }),
    index,
    ...RECIPES.map((r) => recipeCard(r, scope)),
  );
}

function recipeCard(recipe, scope) {
  return h(
    "article",
    {
      class: "card recipe",
      attrs: { id: `recipe-${recipe.id}`, "aria-labelledby": `recipe-${recipe.id}-title` },
    },
    h(
      "div",
      { class: "recipe-head" },
      h("span", { class: "recipe-icon" }, icon(recipe.icon, { size: 20 })),
      h(
        "div",
        {},
        h("h3", {
          class: "recipe-title",
          text: recipe.title,
          attrs: { id: `recipe-${recipe.id}-title` },
        }),
        h("p", { class: "recipe-intro", text: recipe.intro }),
      ),
      recipe.time ? badge(recipe.time, "neutral", "clock") : null,
    ),
    h(
      "ol",
      { class: "recipe-steps" },
      recipe.steps.map((step, index) => recipeStep(step, index, scope)),
    ),
  );
}

function recipeStep(step, index, scope) {
  const doneEl = h(
    "span",
    { class: "step-done", attrs: { hidden: true } },
    icon("check-circle", { size: 16 }),
    h("span", { text: "Already running" }),
  );
  const controls = h("div", { class: "step-do" });
  if (step.do?.action) {
    const action = store.action(step.do.action);
    add(
      controls,
      scope.use(
        actionButton(step.do.action, {
          label:
            action?.button && action.title
              ? action.title
              : (action?.title ?? step.text.replace(/\.$/, "")),
          variant: "primary",
          size: "sm",
          params: step.do.params ?? {},
        }),
      ),
    );
  }
  const openTarget = step.open ?? step.do?.open;
  if (openTarget) {
    const label = {
      web: "Open the web app",
      signin: "Open the sign-in page",
      product: "Open the product",
      admin: "Open /admin",
    }[openTarget];
    const openButton = button({
      label,
      icon: "external",
      size: "sm",
      variant: "secondary",
      onClick: () => openUrl(targetUrl(openTarget).url),
      attrs: { "aria-label": `${label} (opens in your browser)` },
    });
    const sync = () => {
      const target = targetUrl(openTarget);
      openButton.disabled = !target.up;
      openButton.title = target.up
        ? target.url
        : openTarget === "web"
          ? "Start everything first"
          : "Start the product first";
    };
    sync();
    scope.add(store.on("parts", sync));
    add(controls, openButton);
  }
  if (step.go) {
    add(
      controls,
      h(
        "a",
        { class: "btn btn-secondary btn-sm", attrs: { href: step.go } },
        h("span", { class: "label", text: "Go there" }),
        icon("arrow-right", { size: 14 }),
      ),
    );
  }
  if (step.copy) {
    add(
      controls,
      h("code", { class: "copy-value", text: step.copy }),
      copyButton(step.copy, { label: "Copy", variant: "secondary" }),
    );
  }
  if (step.done) {
    const sync = () => {
      doneEl.hidden = store.state.parts[step.done]?.state !== "running";
    };
    sync();
    scope.add(store.on("parts", sync));
  }
  return h(
    "li",
    { class: "recipe-step" },
    h("span", { class: "step-num", text: String(index + 1), attrs: { "aria-hidden": "true" } }),
    h(
      "div",
      { class: "step-body" },
      h("p", { class: "step-text", text: step.text }),
      step.detail ? h("p", { class: "step-detail", text: step.detail }) : null,
      doneEl,
    ),
    controls.childElementCount ? controls : null,
  );
}

// ---- glossary -------------------------------------------------------------------------------------

function glossary() {
  let query = "";
  const list = h("dl", { class: "glossary" });
  const draw = () => {
    const shown = GLOSSARY.filter(
      (g) => !query || `${g.term} ${g.text}`.toLowerCase().includes(query),
    );
    put(
      list,
      ...shown.flatMap((g) => [
        h("dt", { class: "glossary-term", attrs: { id: g.id } }, g.term),
        h("dd", { class: "glossary-text", text: g.text }),
      ]),
    );
    if (!shown.length) add(list, h("p", { class: "muted", text: "No word matches." }));
  };
  draw();
  return h(
    "div",
    { class: "guide-section" },
    heading("Glossary", "glossary-title"),
    h("p", {
      class: "guide-lead",
      text: "The words this app and the project use, in plain language. Words with a dotted underline elsewhere in the app link here.",
    }),
    h("input", {
      class: "input search-input",
      attrs: {
        type: "search",
        placeholder: "Find a word",
        "aria-label": "Find a word in the glossary",
        autocomplete: "off",
      },
      on: {
        input: (e) => {
          query = e.target.value.trim().toLowerCase();
          draw();
        },
      },
    }),
    list,
  );
}

// ---- trouble ------------------------------------------------------------------------------------

function trouble(scope) {
  return h(
    "div",
    { class: "guide-section" },
    heading("When something goes wrong", "trouble-title"),
    h("p", {
      class: "guide-lead",
      text: "The common problems, why they happen and what fixes them. A failed action also says this where it happened.",
    }),
    h(
      "div",
      { class: "trouble-list" },
      TROUBLE.map((t, index) =>
        h(
          "article",
          { class: "card trouble", attrs: { id: `trouble-${index}` } },
          h(
            "h3",
            { class: "trouble-title" },
            icon("warning", { size: 16 }),
            h("span", { text: t.title }),
          ),
          h("p", { class: "trouble-why" }, h("strong", { text: "Why: " }), t.why),
          h("p", { class: "trouble-fix" }, h("strong", { text: "Fix: " }), t.fix),
          t.action || t.go
            ? h(
                "div",
                { class: "trouble-actions" },
                t.action
                  ? scope.use(actionButton(t.action, { variant: "primary", size: "sm" }))
                  : null,
                t.go
                  ? h(
                      "a",
                      { class: "btn btn-secondary btn-sm", attrs: { href: t.go } },
                      h("span", { class: "label", text: "Go there" }),
                      icon("arrow-right", { size: 14 }),
                    )
                  : null,
              )
            : null,
        ),
      ),
    ),
  );
}

// ---- never ------------------------------------------------------------------------------------------

function never() {
  return h(
    "div",
    { class: "guide-section" },
    heading("What this app will never do", "never-title"),
    h("p", {
      class: "guide-lead",
      text: "These rules are checked where each program starts, not only when you press a button, so no button can get around them.",
    }),
    h(
      "ul",
      { class: "never-list", attrs: { role: "list" } },
      NEVER.map((item) =>
        h(
          "li",
          { class: "card never" },
          h("span", { class: "never-icon" }, icon("shield", { size: 18 })),
          h(
            "div",
            {},
            h("h3", {
              class: "never-title",
              text: `Never: ${item.title.charAt(0).toLowerCase()}${item.title.slice(1)}`,
            }),
            h("p", { text: item.text }),
          ),
        ),
      ),
    ),
  );
}

// ---- more to read ---------------------------------------------------------------------------------

function more(scope) {
  const docs = h("ul", { class: "doc-list", attrs: { role: "list" } });
  const github = h("div", { class: "github" });
  const drawDocs = (items) => {
    put(
      docs,
      ...items.map((doc) =>
        h(
          "li",
          { class: "doc-item" },
          icon(doc.kind === "folder" ? "folder" : "file", { size: 16 }),
          h("span", { class: "doc-label", text: doc.label }),
          h("code", { class: "doc-path", text: doc.path }),
          doc.id
            ? button({
                label: "Open",
                icon: "external",
                size: "sm",
                attrs: { "aria-label": `Open ${doc.label}` },
                onClick: async () => {
                  try {
                    await api.openDoc(doc.id);
                    toast({ level: "success", title: `Opened ${doc.label}` });
                  } catch (error) {
                    showRequestError(error);
                  }
                },
              })
            : doc.url
              ? externalLink(doc.url, "Open", {
                  class: "btn btn-secondary btn-sm",
                  ariaLabel: `Open ${doc.label} (opens in your browser)`,
                })
              : null,
        ),
      ),
    );
  };
  drawDocs(DOCS_FALLBACK);
  api.docs().then(
    (data) => {
      const items = (data.docs ?? []).map((d) => ({
        id: d.id ? String(d.id) : "",
        kind: String(d.kind ?? "doc"),
        label: String(d.label ?? d.path ?? ""),
        path: String(d.path ?? ""),
        url: d.url ? String(d.url) : "",
      }));
      if (items.length) drawDocs(items);
    },
    () => {},
  );
  // one read at a time; a github event that lands mid-read makes one more read after it, so a
  // late answer from an older read never covers a newer one
  const readGithub = oneAtATime(() =>
    api.github().then(
      (data) => {
        if (data.loading) {
          put(github, h("p", { class: "muted", text: "Reading GitHub…" }));
          return;
        }
        const links = (data.links ?? []).map((l) =>
          externalLink(String(l.url), String(l.label), { class: "chip-link" }),
        );
        const prs = (data.prs ?? []).map((pr) =>
          h(
            "li",
            { class: "pr" },
            icon("pull-request", { size: 16 }),
            externalLink(String(pr.url), `#${pr.number} ${pr.title}`),
            pr.checks
              ? badge(
                  String(pr.checks),
                  pr.checks === "passing"
                    ? "success"
                    : pr.checks === "failing"
                      ? "danger"
                      : "neutral",
                )
              : null,
          ),
        );
        put(
          github,
          links.length ? h("div", { class: "link-row" }, links) : null,
          prs.length ? h("ul", { class: "pr-list", attrs: { role: "list" } }, prs) : null,
          data.available === false && data.reason
            ? banner({
                tone: "info",
                title: "Pull requests and CI are not shown",
                body: data.reason,
              })
            : null,
        );
      },
      () => put(github, h("p", { class: "muted", text: "GitHub could not be read." })),
    ),
  );
  readGithub();
  scope.add(store.on("event:github", () => readGithub()));
  return h(
    "div",
    { class: "guide-section" },
    heading("More to read", "more-title"),
    h("p", {
      class: "guide-lead",
      text: "The project's own guides, for when you want the details. They open in your editor or browser.",
    }),
    docs,
    h("h3", { class: "guide-sub", text: "On GitHub" }),
    github,
    h("h3", { class: "guide-sub", text: "The tour" }),
    h("p", { text: "Five short steps around this window. It takes a minute." }),
    button({
      label: "Take the tour",
      icon: "sparkles",
      variant: "secondary",
      onClick: () => startTour(),
    }),
  );
}
