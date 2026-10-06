// The building blocks every view uses: buttons, badges, banners, progress, skeletons, the output
// view, dialogs and toasts. Nothing here knows about the helper or the store.

import { add, copyText, cx, frameBatcher, h, put, reducedMotion, uid, withIcon } from "./dom.js";
import { icon } from "./icons.js";
import { GLOSSARY, termId } from "./guide.js";
import { SAFETY } from "./model.js";

export function button({
  label = "",
  icon: iconName = "",
  variant = "secondary",
  size = "md",
  onClick,
  disabled = false,
  title = "",
  ariaLabel = "",
  type = "button",
  attrs = {},
  data = {},
  className = "",
  iconOnly = false,
}) {
  const el = h(
    "button",
    {
      class: cx("btn", `btn-${variant}`, `btn-${size}`, className, { "btn-icon": iconOnly }),
      attrs: {
        type,
        title: title || (iconOnly ? label : ""),
        "aria-label": ariaLabel || (iconOnly ? label : ""),
        ...attrs,
      },
      data,
      props: { disabled },
      on: onClick ? { click: (event) => press(el, onClick, event) } : {},
    },
    iconName ? icon(iconName, { size: size === "lg" ? 20 : 16 }) : null,
    iconOnly ? null : h("span", { class: "label", text: label }),
  );
  return el;
}

/**
 * A press of a button whose work takes a moment (a preview, a question, a request): the button
 * is busy and ignores further presses until that work is done, so a double click does one thing.
 */
function press(el, onClick, event) {
  if (el.dataset.pressed === "true") {
    event.preventDefault();
    return;
  }
  const result = onClick(event);
  if (!result || typeof result.then !== "function") return;
  el.dataset.pressed = "true";
  el.setAttribute("aria-busy", "true");
  const owned = !el.hasAttribute("aria-disabled");
  if (owned) el.setAttribute("aria-disabled", "true");
  const done = () => {
    delete el.dataset.pressed;
    el.removeAttribute("aria-busy");
    if (owned) el.removeAttribute("aria-disabled");
  };
  result.then(done, done);
}

/** Marks a button as working: disabled, aria-busy, with a spinner in place of its icon. */
export function setBusy(el, busy) {
  el.toggleAttribute("aria-busy", busy);
  el.disabled = busy || el.dataset.disabled === "true";
  el.classList.toggle("is-busy", busy);
}

export function linkButton({
  label,
  href,
  icon: iconName = "",
  variant = "secondary",
  size = "md",
  external = false,
}) {
  return h(
    "a",
    {
      class: cx("btn", `btn-${variant}`, `btn-${size}`),
      attrs: {
        href,
        ...(external
          ? {
              target: "_blank",
              rel: "noopener noreferrer",
              "aria-label": `${label} (opens in your browser)`,
            }
          : {}),
      },
    },
    iconName ? icon(iconName, { size: 16 }) : null,
    h("span", { class: "label", text: label }),
    external ? icon("external", { size: 14 }) : null,
  );
}

export function badge(text, tone = "neutral", iconName = "") {
  return h(
    "span",
    { class: cx("badge", `tone-${tone}`) },
    iconName ? icon(iconName, { size: 12 }) : null,
    h("span", { text }),
  );
}

export function safetyBadge(safety) {
  const meta = SAFETY[safety] ?? SAFETY.safe;
  const el = badge(meta.label, meta.tone, meta.icon);
  el.classList.add("safety");
  el.title = meta.plain;
  return el;
}

/** A coloured dot with its words: the words carry the meaning, the colour only helps. */
export function statusChip(state, label) {
  return h(
    "span",
    { class: "status-chip", data: { state } },
    h("span", { class: "dot", attrs: { "aria-hidden": "true" } }),
    h("span", { class: "status-text", text: label }),
  );
}

export function banner({ tone = "info", title = "", body = "", items = [], actions = [], role }) {
  const icons = {
    info: "info",
    success: "check-circle",
    warning: "warning",
    danger: "alert-circle",
    neutral: "info",
  };
  return h(
    "div",
    {
      class: cx("banner", `tone-${tone}`),
      attrs: { role: role ?? (tone === "danger" ? "alert" : "status") },
    },
    icon(icons[tone] ?? "info", { size: 18 }),
    h(
      "div",
      { class: "banner-body" },
      title ? h("p", { class: "banner-title", text: title }) : null,
      body ? h("p", { class: "banner-text", text: body }) : null,
      items.length
        ? h(
            "ul",
            { class: "banner-list" },
            items.map((t) => h("li", { text: t })),
          )
        : null,
      actions.length ? h("div", { class: "banner-actions" }, actions) : null,
    ),
  );
}

export function progressBar({ label = "Progress" } = {}) {
  const bar = h("div", { class: "progress-fill" });
  const el = h(
    "div",
    {
      class: "progress",
      attrs: {
        role: "progressbar",
        "aria-label": label,
        "aria-valuemin": "0",
        "aria-valuemax": "100",
      },
    },
    bar,
  );
  return {
    el,
    set(value) {
      if (value === null || value === undefined) {
        el.classList.add("indeterminate");
        el.removeAttribute("aria-valuenow");
        return;
      }
      el.classList.remove("indeterminate");
      const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
      bar.style.setProperty("--value", `${pct}%`);
      el.setAttribute("aria-valuenow", String(pct));
    },
  };
}

export function spinner(label = "") {
  return h("span", {
    class: "spinner",
    attrs: label ? { role: "img", "aria-label": label } : { "aria-hidden": "true" },
  });
}

export function skeleton(kind = "card", count = 1) {
  const pieces = [];
  for (let i = 0; i < count; i += 1) {
    if (kind === "line") pieces.push(h("span", { class: "skel skel-line" }));
    else if (kind === "row") pieces.push(h("span", { class: "skel skel-row" }));
    else
      pieces.push(
        h(
          "div",
          { class: "card skel-card", attrs: { "aria-hidden": "true" } },
          h("span", { class: "skel skel-title" }),
          h("span", { class: "skel skel-line" }),
          h("span", { class: "skel skel-line short" }),
          h("span", { class: "skel skel-button" }),
        ),
      );
  }
  return h(
    "div",
    {
      class: cx("skel-group", `skel-${kind}s`),
      attrs: { role: "status", "aria-label": "Loading" },
    },
    pieces,
  );
}

export function emptyState({ icon: iconName = "info", title, body = "", actions = [] }) {
  return h(
    "div",
    { class: "empty" },
    h("span", { class: "empty-icon" }, icon(iconName, { size: 24 })),
    h("p", { class: "empty-title", text: title }),
    body ? h("p", { class: "empty-text", text: body }) : null,
    actions.length ? h("div", { class: "empty-actions" }, actions) : null,
  );
}

/** A heading row for a view: title, a plain line under it, and actions on the right. */
export function viewHeader({ title, lead = "", actions = [], eyebrow = "" }) {
  return h(
    "header",
    { class: "view-header" },
    h(
      "div",
      { class: "view-heading" },
      eyebrow ? h("p", { class: "eyebrow", text: eyebrow }) : null,
      h("h1", { class: "view-title", text: title, attrs: { tabindex: "-1" } }),
      lead ? h("p", { class: "view-lead" }, lead) : null,
    ),
    actions.length ? h("div", { class: "view-actions" }, actions) : null,
  );
}

export function section({
  title,
  lead = "",
  id = "",
  actions = [],
  children = [],
  className = "",
}) {
  const headingId = id ? `${id}-title` : uid("section");
  return h(
    "section",
    { class: cx("section", className), attrs: { id: id || null, "aria-labelledby": headingId } },
    h(
      "div",
      { class: "section-head" },
      h(
        "div",
        {},
        h("h2", { class: "section-title", text: title, attrs: { id: headingId } }),
        lead ? h("p", { class: "section-lead" }, lead) : null,
      ),
      actions.length ? h("div", { class: "section-actions" }, actions) : null,
    ),
    children,
  );
}

/** A show/hide control for a region, with aria-expanded. */
export function disclosure({ label, openLabel = "", content, open = false, className = "" }) {
  const regionId = uid("region");
  const region = h("div", { class: "disclosure-region", attrs: { id: regionId, hidden: !open } });
  let filled = false;
  const text = h("span", { class: "label", text: open && openLabel ? openLabel : label });
  const chevron = icon("chevron-right", { size: 14 });
  const toggle = h(
    "button",
    {
      class: cx("disclosure", className),
      attrs: { type: "button", "aria-expanded": String(open), "aria-controls": regionId },
      on: {
        click: () => setOpen(toggle.getAttribute("aria-expanded") !== "true"),
      },
    },
    chevron,
    text,
  );
  function setOpen(value) {
    if (value && !filled) {
      add(region, typeof content === "function" ? content() : content);
      filled = true;
    }
    toggle.setAttribute("aria-expanded", String(value));
    region.hidden = !value;
    text.textContent = value && openLabel ? openLabel : label;
  }
  if (open) setOpen(true);
  return { toggle, region, setOpen, el: h("div", { class: "disclosure-wrap" }, toggle, region) };
}

const GLOSSARY_BY_ID = new Map(GLOSSARY.map((entry) => [entry.id, entry]));

/** A word from the glossary, linked to its entry; its meaning shows on hover and focus. */
export function term(word, key = word) {
  const entry = GLOSSARY_BY_ID.get(termId(key));
  if (!entry) return word;
  return h("a", {
    class: "term",
    text: word,
    attrs: { href: `#/guide/glossary/${entry.id}`, "data-term": entry.id },
  });
}

/** Plain text with some words linked to the glossary: rich("Start {Docker}.") */
export function rich(text) {
  const parts = [];
  const pattern = /\{([^}|]+)(?:\|([^}]+))?\}/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(term(match[1], match[2] ?? match[1]));
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function copyButton(getText, { label = "Copy", size = "sm", variant = "ghost" } = {}) {
  const el = button({
    label,
    icon: "copy",
    size,
    variant,
    onClick: async () => {
      const ok = await copyText(typeof getText === "function" ? getText() : getText);
      const text = el.querySelector(".label");
      if (text) {
        text.textContent = ok ? "Copied" : "Could not copy";
        window.setTimeout(() => (text.textContent = label), 1600);
      }
      announce(ok ? "Copied to the clipboard" : "Could not copy");
    },
  });
  return el;
}

// ---- the output of a run or a log -----------------------------------------------------------

/**
 * A bounded, scrolling view of output lines. It follows new lines while the reader is at the
 * bottom, and offers "Jump to the latest" when they have scrolled up.
 */
export function outputView({ label = "Output", max = 4000, wrap = false } = {}) {
  const body = h("div", {
    class: cx("output-body", { wrap }),
    attrs: { role: "log", "aria-live": "off", "aria-label": label, tabindex: "0" },
  });
  const note = h("p", { class: "output-note", attrs: { hidden: true } });
  const jump = button({
    label: "Jump to the latest",
    icon: "chevron-down",
    size: "sm",
    variant: "secondary",
    className: "output-jump",
    onClick: () => {
      follow = true;
      body.scrollTop = body.scrollHeight;
      jump.hidden = true;
    },
  });
  jump.hidden = true;
  let follow = true;
  let count = 0;
  let dropped = 0;
  body.addEventListener("scroll", () => {
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
    follow = atBottom;
    if (atBottom) jump.hidden = true;
  });

  const lineEl = (line) =>
    h("div", {
      class: "ln",
      text: line.text === "" ? " " : line.text,
      data: line.tag ? { tag: line.tag } : {},
    });

  const flush = frameBatcher((batches) => {
    const fragment = document.createDocumentFragment();
    for (const lines of batches) for (const line of lines) add(fragment, lineEl(line));
    add(body, fragment);
    count = body.childElementCount;
    if (count > max) {
      const extra = count - max;
      for (let i = 0; i < extra; i += 1) body.firstElementChild?.remove();
      dropped += extra;
    }
    showNote();
    if (follow) body.scrollTop = body.scrollHeight;
    else jump.hidden = false;
  });

  function showNote() {
    note.hidden = dropped === 0;
    note.textContent = dropped
      ? `${dropped.toLocaleString()} earlier lines are not shown here. Copy takes what is shown.`
      : "";
  }

  const el = h("div", { class: "output" }, note, body, jump);
  return {
    el,
    body,
    append(lines) {
      if (lines?.length) flush(lines);
    },
    reset(lines = [], droppedBefore = 0) {
      put(body, ...lines.map(lineEl));
      dropped = droppedBefore;
      showNote();
      follow = true;
      body.scrollTop = body.scrollHeight;
      jump.hidden = true;
    },
    text() {
      return [...body.children].map((line) => line.textContent).join("\n");
    },
    setFollow(value) {
      follow = value;
      if (value) body.scrollTop = body.scrollHeight;
    },
  };
}

// ---- dialogs ----------------------------------------------------------------------------------

let dialogOpen = false;

/**
 * A modal dialog (the platform's <dialog>, so focus stays inside and Escape closes it).
 * build(close) returns the body; actions are [{ label, value, variant, autofocus, disabled }].
 * Resolves with the chosen value, or null when dismissed.
 */
export function openDialog({
  title,
  tone = "",
  iconName = "",
  build,
  actions = [],
  size = "md",
  label = "",
}) {
  // one question at a time: a second one while one is open is answered "no" at once
  if (dialogOpen) return Promise.resolve(null);
  dialogOpen = true;
  return new Promise((resolve, reject) => {
    try {
      const titleId = uid("dialog-title");
      const bodyId = uid("dialog-body");
      let settled = false;
      const dialog = h("dialog", {
        class: cx("dialog", `dialog-${size}`, tone ? `tone-${tone}` : ""),
        attrs: {
          "aria-labelledby": titleId,
          "aria-describedby": bodyId,
          "aria-label": label || null,
        },
      });
      // The dialog closes (and the platform puts focus back where it was) before the caller
      // hears the answer, so whatever the caller focuses next keeps the focus.
      const close = (value) => {
        if (settled) return;
        settled = true;
        dialog.classList.add("closing");
        window.setTimeout(
          () => {
            if (dialog.open) dialog.close();
            dialog.remove();
            dialogOpen = false;
            resolve(value);
          },
          reducedMotion() ? 0 : 120,
        );
      };
      const body = h(
        "div",
        { class: "dialog-body", attrs: { id: bodyId } },
        build ? build(close) : null,
      );
      const footer = h(
        "div",
        { class: "dialog-footer" },
        actions.map((action) => {
          const el = button({
            label: action.label,
            variant: action.variant ?? "secondary",
            icon: action.icon ?? "",
            onClick: () =>
              close(typeof action.value === "function" ? action.value() : action.value),
            data: { value: String(action.key ?? action.label) },
          });
          if (action.autofocus) el.setAttribute("autofocus", "");
          if (action.disabled) el.disabled = true;
          if (action.ref) action.ref(el);
          return el;
        }),
      );
      add(
        dialog,
        h(
          "div",
          { class: "dialog-head" },
          iconName
            ? h(
                "span",
                { class: cx("dialog-icon", tone ? `tone-${tone}` : "") },
                icon(iconName, { size: 22 }),
              )
            : null,
          h("h2", { class: "dialog-title", text: title, attrs: { id: titleId } }),
          button({
            label: "Close",
            icon: "close",
            iconOnly: true,
            variant: "ghost",
            size: "sm",
            className: "dialog-close",
            onClick: () => close(null),
          }),
        ),
        body,
        actions.length ? footer : null,
      );
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        close(null);
      });
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) close(null);
      });
      add(document.body, dialog);
      dialog.showModal();
      const focus =
        dialog.querySelector("[autofocus]") ?? dialog.querySelector(".dialog-footer .btn");
      focus?.focus();
    } catch (error) {
      // a dialog that could not be built must not keep the next one from opening
      dialogOpen = false;
      reject(error);
    }
  });
}

// ---- toasts and announcements -----------------------------------------------------------------

let toastRegion = null;
let liveRegion = null;

export function mountToasts(region, live) {
  toastRegion = region;
  liveRegion = live;
}

/** Says something to screen readers without showing it. */
export function announce(text) {
  if (!liveRegion) return;
  liveRegion.textContent = "";
  window.setTimeout(() => (liveRegion.textContent = text), 30);
}

/**
 * A toast in the corner: { level: success | info | warning | error, title, body, actions }.
 * Errors stay until closed; the others leave after a few seconds unless hovered or focused.
 */
export function toast({ level = "info", title, body = "", actions = [], timeout }) {
  if (!toastRegion) return null;
  const icons = {
    success: "check-circle",
    info: "info",
    warning: "warning",
    error: "alert-circle",
  };
  const tone =
    { success: "success", info: "info", warning: "warning", error: "danger" }[level] ?? "info";
  const el = h(
    "div",
    { class: cx("toast", `tone-${tone}`), attrs: { role: level === "error" ? "alert" : "status" } },
    h("span", { class: "toast-icon" }, icon(icons[level] ?? "info", { size: 20 })),
    h(
      "div",
      { class: "toast-body" },
      h("p", { class: "toast-title", text: title }),
      body ? h("p", { class: "toast-text", text: body }) : null,
      actions.length
        ? h(
            "div",
            { class: "toast-actions" },
            actions.map((a) =>
              button({
                label: a.label,
                size: "sm",
                variant: a.variant ?? "secondary",
                icon: a.icon ?? "",
                onClick: () => {
                  a.onClick();
                  dismiss();
                },
              }),
            ),
          )
        : null,
    ),
    button({
      label: "Dismiss",
      icon: "close",
      iconOnly: true,
      size: "sm",
      variant: "ghost",
      className: "toast-close",
      onClick: () => dismiss(),
    }),
  );
  let timer = 0;
  const wait = timeout ?? (level === "error" ? 0 : level === "warning" ? 9000 : 6000);
  const arm = () => {
    if (wait) timer = window.setTimeout(dismiss, wait);
  };
  const disarm = () => window.clearTimeout(timer);
  el.addEventListener("mouseenter", disarm);
  el.addEventListener("mouseleave", arm);
  el.addEventListener("focusin", disarm);
  el.addEventListener("focusout", arm);
  function dismiss() {
    disarm();
    el.classList.add("leaving");
    window.setTimeout(() => el.remove(), 160);
  }
  add(toastRegion, el);
  while (toastRegion.childElementCount > 4) toastRegion.firstElementChild?.remove();
  arm();
  return { el, dismiss };
}

export function tooltipFor(el, text) {
  el.setAttribute("title", text);
  return el;
}

export { withIcon };
