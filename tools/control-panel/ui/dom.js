// A tiny view helper and the formatting every view shares. Text always goes in as text
// (textContent), never as markup: log lines and command output come from programs.

import { icon } from "./icons.js";

/**
 * h("button", { class: "btn", on: { click }, attrs: { "aria-label": "Close" } }, "Close")
 * Props: class, text, attrs, data (dataset), on (listeners), props (DOM properties),
 * vars (CSS custom properties, set through the CSSOM), ref (called with the element).
 * Children: nodes, strings, numbers, arrays, null/false (skipped).
 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  if (props.class) el.className = Array.isArray(props.class) ? cx(...props.class) : props.class;
  if (props.text !== undefined && props.text !== null) el.textContent = String(props.text);
  for (const [name, value] of Object.entries(props.attrs ?? {})) {
    if (value === false || value === null || value === undefined) continue;
    el.setAttribute(name, value === true ? "" : String(value));
  }
  for (const [name, value] of Object.entries(props.data ?? {})) {
    if (value !== undefined && value !== null) el.dataset[name] = String(value);
  }
  for (const [name, value] of Object.entries(props.props ?? {})) el[name] = value;
  for (const [name, value] of Object.entries(props.vars ?? {})) el.style.setProperty(name, value);
  for (const [event, handler] of Object.entries(props.on ?? {}))
    el.addEventListener(event, handler);
  append(el, children);
  if (props.ref) props.ref(el);
  return el;
}

/** Appends children the way h() takes them. */
export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Element.append, skipping empty values and flattening arrays (the DOM's own writes "null"). */
export function add(el, ...children) {
  return append(el, children);
}

/** Element.replaceChildren with the same care as add(). */
export function put(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

/** Class names from strings and { name: condition } objects. */
export function cx(...parts) {
  const names = [];
  for (const part of parts) {
    if (!part) continue;
    if (typeof part === "string") names.push(part);
    else for (const [name, on] of Object.entries(part)) if (on) names.push(name);
  }
  return names.join(" ");
}

/** An icon followed by a label, for buttons and links. */
export function withIcon(name, label, options = {}) {
  return [icon(name, options), label ? h("span", { class: "label", text: label }) : null];
}

export function visuallyHidden(text) {
  return h("span", { class: "sr-only", text });
}

/** Text with its first letter capitalised and the rest as written ("start Docker"). */
export function sentence(text) {
  const value = String(text ?? "").trim();
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

/** A step's label as a sentence, except a command, which keeps its own spelling: "make dev". */
export function stepLabel(text) {
  const value = String(text ?? "").trim();
  return /^(make|colima|pnpm|docker|uv|git|pg_dump|pg_restore|rpk|npx|node|python3?)\b/.test(value)
    ? value
    : sentence(value);
}

export function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

/** Seconds as "45 s", "2 min 05 s", "1 h 02 min". */
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes < 60) return `${minutes} min ${String(secs).padStart(2, "0")} s`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

/** A short "how long" for running processes: "3 min", "2 h 10 min", "4 days". */
export function formatElapsed(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
  return `${Math.floor(hours / 24)} days`;
}

/** Epoch seconds (or milliseconds) as "just now", "2 min ago", "at 14:05", "on 3 Oct". */
export function formatAgo(when, now = Date.now()) {
  if (!when) return "";
  const ms = when < 1e12 ? when * 1000 : when;
  const diff = Math.max(0, now - ms) / 1000;
  if (diff < 10) return "just now";
  if (diff < 60) return `${Math.floor(diff)} s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  const date = new Date(ms);
  const today = new Date(now);
  if (date.toDateString() === today.toDateString()) {
    return `at ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }
  return `on ${date.toLocaleDateString([], { day: "numeric", month: "short" })}`;
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "number") return value.toLocaleString("en-IN");
  return String(value);
}

let counter = 0;
export function uid(prefix = "id") {
  counter += 1;
  return `${prefix}-${counter}`;
}

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Copies text; true when it worked. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h("textarea", { class: "sr-only", props: { value: text } });
    document.body.append(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
    return ok;
  }
}

export function debounce(fn, wait) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

/**
 * One read at a time, and none lost: a call that comes while a read is on its way (an event
 * that lands mid-load) is not dropped; fn runs once more when that read is done, with the
 * arguments of the latest such call. Every caller gets the promise of the read that answers it.
 */
export function oneAtATime(fn) {
  let running = null;
  let again = null;
  let nextArgs = [];
  const run = (...args) => {
    if (running) {
      nextArgs = args;
      again ??= running.then(
        () => run(...nextArgs),
        () => run(...nextArgs),
      );
      return again;
    }
    running = Promise.resolve()
      .then(() => fn(...args))
      .finally(() => {
        running = null;
        again = null;
      });
    return running;
  };
  return run;
}

/** Calls fn at most once per animation frame with every value queued since the last call. */
export function frameBatcher(fn) {
  let queue = [];
  let pending = false;
  return (item) => {
    queue.push(item);
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(() => {
      const items = queue;
      queue = [];
      pending = false;
      fn(items);
    });
  };
}

/** Keeps focus inside a container while Tab moves through it (for non-modal layers). */
export function focusables(root) {
  return [
    ...root.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ].filter((el) => !el.closest("[hidden]") && el.getClientRects().length > 0);
}

/** A safe external link: opens outside the app window (the shell hands it to the browser). */
export function externalLink(url, label, options = {}) {
  return h(
    "a",
    {
      class: options.class ?? "link",
      attrs: {
        href: url,
        target: "_blank",
        rel: "noopener noreferrer",
        "aria-label": options.ariaLabel ?? `${label} (opens in your browser)`,
      },
    },
    h("span", { class: "label", text: label }),
    icon("external", { size: 14 }),
  );
}
