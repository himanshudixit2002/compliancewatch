// The first-launch tour: five steps that point at the parts of the window, skippable, and
// replayable from the Guide.

import { add, focusables, h, reducedMotion } from "./dom.js";
import { TOUR } from "./guide.js";
import { button } from "./ui.js";

let active = null;

export function startTour({ onDone } = {}) {
  if (active) return;
  let index = 0;
  const previousFocus = document.activeElement;
  const spot = h("div", { class: "tour-spot", attrs: { "aria-hidden": "true" } });
  const counter = h("p", { class: "tour-count" });
  const titleEl = h("h2", { class: "tour-title", attrs: { id: "tour-title" } });
  const textEl = h("p", { class: "tour-text", attrs: { id: "tour-text" } });
  const back = button({
    label: "Back",
    size: "sm",
    variant: "ghost",
    onClick: () => go(index - 1),
  });
  const next = button({
    label: "Next",
    size: "sm",
    variant: "primary",
    onClick: () => (index === TOUR.length - 1 ? finish(true) : go(index + 1)),
  });
  const skip = button({
    label: "Skip the tour",
    size: "sm",
    variant: "ghost",
    className: "tour-skip",
    onClick: () => finish(false),
  });
  const dots = h(
    "div",
    { class: "tour-dots", attrs: { "aria-hidden": "true" } },
    TOUR.map(() => h("span", { class: "tour-dot" })),
  );
  const card = h(
    "div",
    {
      class: "tour-card",
      attrs: {
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "tour-title",
        "aria-describedby": "tour-text",
        tabindex: "-1",
      },
    },
    counter,
    titleEl,
    textEl,
    h("div", { class: "tour-foot" }, dots, h("div", { class: "tour-buttons" }, skip, back, next)),
  );
  const layer = h(
    "div",
    { class: "tour-layer", data: { testid: "tour" } },
    h("div", { class: "tour-shade" }),
    spot,
    card,
  );

  function place() {
    const step = TOUR[index];
    const target = document.querySelector(step.target);
    const rect = target?.getBoundingClientRect();
    const visible = rect && rect.width > 0 && rect.height > 0;
    layer.classList.toggle("no-target", !visible);
    const pad = 8;
    if (visible) {
      spot.style.setProperty("--x", `${rect.left - pad}px`);
      spot.style.setProperty("--y", `${rect.top - pad}px`);
      spot.style.setProperty("--w", `${rect.width + pad * 2}px`);
      spot.style.setProperty("--h", `${rect.height + pad * 2}px`);
    }
    const cardRect = card.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let x = (vw - cardRect.width) / 2;
    let y = (vh - cardRect.height) / 2;
    if (visible) {
      const below = rect.bottom + pad + 12;
      const above = rect.top - pad - 12 - cardRect.height;
      if (below + cardRect.height < vh - 12) y = below;
      else if (above > 12) y = above;
      else y = Math.min(vh - cardRect.height - 12, Math.max(12, rect.top));
      x = rect.left + rect.width / 2 - cardRect.width / 2;
      if (
        y === Math.min(vh - cardRect.height - 12, Math.max(12, rect.top)) &&
        rect.right + cardRect.width + 24 < vw
      ) {
        x = rect.right + 20;
      }
    }
    x = Math.min(vw - cardRect.width - 12, Math.max(12, x));
    card.style.setProperty("--x", `${Math.round(x)}px`);
    card.style.setProperty("--y", `${Math.round(y)}px`);
  }

  function go(to) {
    index = Math.max(0, Math.min(TOUR.length - 1, to));
    const step = TOUR[index];
    if (step.route && !window.location.hash.startsWith(step.route))
      window.location.hash = step.route;
    counter.textContent = `${index + 1} of ${TOUR.length}`;
    titleEl.textContent = step.title;
    textEl.textContent = step.text;
    back.hidden = index === 0;
    next.querySelector(".label").textContent = index === TOUR.length - 1 ? "Done" : "Next";
    [...dots.children].forEach((dot, i) => dot.classList.toggle("on", i === index));
    const target = document.querySelector(step.target);
    if (target && !reducedMotion()) target.scrollIntoView({ block: "nearest" });
    window.requestAnimationFrame(() => {
      place();
      card.focus({ preventScroll: true });
      // from the first placement on, moves between steps glide
      window.requestAnimationFrame(() => layer.classList.add("placed"));
    });
  }

  function finish(completed) {
    const app = document.getElementById("app");
    if (app) app.inert = false;
    window.removeEventListener("resize", place);
    document.removeEventListener("keydown", onKey, true);
    layer.classList.add("leaving");
    window.setTimeout(() => layer.remove(), 160);
    active = null;
    onDone?.(completed);
    if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true });
  }

  function onKey(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      if (index < TOUR.length - 1) go(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (index > 0) go(index - 1);
    } else if (event.key === "Tab") {
      const items = focusables(card);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === card)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  add(document.body, layer);
  const app = document.getElementById("app");
  if (app) app.inert = true;
  window.addEventListener("resize", place);
  document.addEventListener("keydown", onKey, true);
  active = { finish };
  go(0);
}

export function tourRunning() {
  return active !== null;
}
