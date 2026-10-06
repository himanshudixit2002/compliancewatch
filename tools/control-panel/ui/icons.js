// The app's icons, drawn for it on a 24-unit grid: strokes in currentColor, round caps and joins.
// Each entry is the inside of an <svg viewBox="0 0 24 24">; icon() wraps it. No icon set, no
// network: everything the window shows is in this folder.

const PATHS = {
  home: '<path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z"/>',
  play: '<path d="M8 5.5v13a.6.6 0 0 0 .9.5l10.2-6.5a.6.6 0 0 0 0-1L8.9 5a.6.6 0 0 0-.9.5z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  power: '<path d="M12 3.5v8"/><path d="M7.1 6.6a7.5 7.5 0 1 0 9.8 0"/>',
  database:
    '<ellipse cx="12" cy="6" rx="7" ry="2.75"/><path d="M5 6v12c0 1.5 3.1 2.75 7 2.75s7-1.25 7-2.75V6"/><path d="M5 12c0 1.5 3.1 2.75 7 2.75s7-1.25 7-2.75"/>',
  checks:
    '<path d="M9 4.5h6"/><rect x="5" y="4.5" width="14" height="16" rx="2"/><path d="m8.5 12.5 2.3 2.3L15.5 10"/>',
  features:
    '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  pipeline:
    '<circle cx="5.5" cy="12" r="2"/><circle cx="18.5" cy="6" r="2"/><circle cx="18.5" cy="18" r="2"/><path d="M7.5 12h3a3 3 0 0 0 3-3V8a2 2 0 0 1 2-2h1"/><path d="M10.5 12a3 3 0 0 1 3 3v1a2 2 0 0 0 2 2h1"/>',
  flag: '<path d="M5.5 21V4.5"/><path d="M5.5 4.5h11l-2.2 4 2.2 4h-11"/>',
  cpu: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/><path d="M10 10h4v4h-4z"/><path d="M9.5 3.5v3M14.5 3.5v3M9.5 17.5v3M14.5 17.5v3M3.5 9.5h3M3.5 14.5h3M17.5 9.5h3M17.5 14.5h3"/>',
  logs: '<path d="M14.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14.5 3.5V8H19"/><path d="M8.5 12.5h7M8.5 16h5"/>',
  terminal:
    '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="m7.5 9.5 3 2.5-3 2.5"/><path d="M12.5 15h4"/>',
  book: '<path d="M12 6.5c-1.6-1.3-3.8-2-6.5-2H4v13h1.5c2.7 0 4.9.7 6.5 2 1.6-1.3 3.8-2 6.5-2H20v-13h-1.5c-2.7 0-4.9.7-6.5 2z"/><path d="M12 6.5v13"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
  "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
  "chevron-left": '<path d="m14.5 6-6 6 6 6"/>',
  "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
  "chevron-up": '<path d="m6 14.5 6-6 6 6"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  external:
    '<path d="M13.5 4.5h6v6"/><path d="M19.5 4.5 11 13"/><path d="M17.5 14v4.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1H10"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  refresh:
    '<path d="M19.5 12a7.5 7.5 0 0 1-13 5.1"/><path d="M4.5 12a7.5 7.5 0 0 1 13-5.1"/><path d="M17.5 3.5v3.5H14"/><path d="M6.5 20.5V17H10"/>',
  warning:
    '<path d="M10.3 4.6 3.2 17a2 2 0 0 0 1.7 3h14.2a2 2 0 0 0 1.7-3L13.7 4.6a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4"/><path d="M12 16.75v.01"/>',
  "alert-circle":
    '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.75v5"/><path d="M12 16.25v.01"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.75v.01"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  "check-circle": '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.25 2.5 2.5 4.75-5"/>',
  "x-circle": '<circle cx="12" cy="12" r="8.5"/><path d="m9.25 9.25 5.5 5.5M14.75 9.25l-5.5 5.5"/>',
  "minus-circle": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  branch:
    '<circle cx="7" cy="5.5" r="2"/><circle cx="7" cy="18.5" r="2"/><circle cx="17" cy="7.5" r="2"/><path d="M7 7.5v9"/><path d="M17 9.5c0 4-4.5 3.5-8.5 7"/>',
  container:
    '<path d="M12 3.5 19.5 7.5v9L12 20.5 4.5 16.5v-9z"/><path d="M4.5 7.5 12 11.5l7.5-4"/><path d="M12 11.5v9"/>',
  server:
    '<rect x="4" y="4.5" width="16" height="6" rx="1.5"/><rect x="4" y="13.5" width="16" height="6" rx="1.5"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>',
  globe:
    '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/><path d="M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5S9.7 5.9 12 3.5z"/>',
  package:
    '<path d="M4.5 7.5 12 3.5l7.5 4v9L12 20.5l-7.5-4z"/><path d="M8.25 5.5 15.75 9.5v3"/><path d="M4.5 7.5 12 11.5l7.5-4"/><path d="M12 11.5v9"/>',
  layers:
    '<path d="m12 3.5 8.5 4.5L12 12.5 3.5 8z"/><path d="m3.5 12 8.5 4.5 8.5-4.5"/><path d="m3.5 16 8.5 4.5 8.5-4.5"/>',
  activity: '<path d="M3.5 12h3.5l2.5-6 5 12 2.5-6h3.5"/>',
  download: '<path d="M12 4v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 19.5h14"/>',
  upload: '<path d="M12 15.5v-11"/><path d="m7.5 9 4.5-4.5L16.5 9"/><path d="M5 19.5h14"/>',
  rotate:
    '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4h4"/><path d="M12 8.5V12l2.5 1.5"/>',
  trash:
    '<path d="M4.5 7h15"/><path d="M9.5 7V5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v2"/><path d="M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.5h6.4a1.5 1.5 0 0 0 1.5-1.5l.8-12"/>',
  key: '<circle cx="8" cy="15.5" r="4"/><path d="m11 12.5 8.5-8.5"/><path d="m16 7 2.5 2.5"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"/>',
  shield:
    '<path d="M12 3.5 19 6v5.5c0 4.3-2.9 7.7-7 9-4.1-1.3-7-4.7-7-9V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
  "shield-off":
    '<path d="M12 3.5 19 6v5.5c0 4.3-2.9 7.7-7 9-4.1-1.3-7-4.7-7-9V6z"/><path d="M12 8.5v4"/><path d="M12 15.5v.01"/>',
  users:
    '<circle cx="9" cy="8.5" r="3.5"/><path d="M3 19.5c.6-3.2 3-5 6-5s5.4 1.8 6 5"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6"/><path d="M18 14.8c1.6.7 2.6 2.4 3 4.7"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20c.8-3.8 3.7-6 7.5-6s6.7 2.2 7.5 6"/>',
  briefcase:
    '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M9 7.5V5.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5.5v2"/><path d="M3.5 12.5h17"/>',
  building:
    '<path d="M5 20.5V5a1.5 1.5 0 0 1 1.5-1.5h7A1.5 1.5 0 0 1 15 5v15.5"/><path d="M15 9.5h3a1.5 1.5 0 0 1 1.5 1.5v9.5"/><path d="M3.5 20.5h17"/><path d="M8.5 7.5h3M8.5 11h3M8.5 14.5h3"/>',
  sparkles:
    '<path d="M10 4.5 11.4 9a2 2 0 0 0 1.3 1.3l4.5 1.4-4.5 1.4a2 2 0 0 0-1.3 1.3L10 18.9l-1.4-4.5a2 2 0 0 0-1.3-1.3l-4.5-1.4 4.5-1.4A2 2 0 0 0 8.6 9z"/><path d="M18 3.5v4M16 5.5h4"/><path d="M18.5 16.5v3M17 18h3"/>',
  zap: '<path d="M13 3.5 5.5 13.5H12l-1 7 7.5-10H12z"/>',
  "arrow-right": '<path d="M4.5 12h15"/><path d="m13.5 6 6 6-6 6"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.8"/><path d="M12 16.75v.01"/>',
  list: '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>',
  pause:
    '<rect x="6.5" y="5.5" width="3.5" height="13" rx="1"/><rect x="14" y="5.5" width="3.5" height="13" rx="1"/>',
  bell: '<path d="M6 10a6 6 0 0 1 12 0c0 5 2 6.5 2 6.5H4s2-1.5 2-6.5z"/><path d="M10 19.5a2.2 2.2 0 0 0 4 0"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  folder:
    '<path d="M3.5 7a1.5 1.5 0 0 1 1.5-1.5h4.2l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v8.5A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
  file: '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z"/><path d="M14 3.5v5h5"/>',
  "pull-request":
    '<circle cx="6.5" cy="5.5" r="2"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="18.5" r="2"/><path d="M6.5 7.5v9"/><path d="M17.5 16.5V9a2.5 2.5 0 0 0-2.5-2.5h-3.5"/><path d="m13.5 4.5-2 2 2 2"/>',
  gauge:
    '<path d="M4.2 16.5a8.5 8.5 0 1 1 15.6 0"/><path d="m12 13.5 3.5-4"/><circle cx="12" cy="14" r="1.25"/>',
  wave: '<path d="M3.5 9c2.8 0 2.8-3 5.6-3s2.8 3 5.6 3 2.8-3 5.6-3"/><path d="M3.5 15c2.8 0 2.8-3 5.6-3s2.8 3 5.6 3 2.8-3 5.6-3"/>',
  inbox:
    '<path d="M4 13.5 6.3 6a1.5 1.5 0 0 1 1.4-1h8.6a1.5 1.5 0 0 1 1.4 1l2.3 7.5"/><path d="M4 13.5V18a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 18v-4.5h-4.5l-1.5 2h-4l-1.5-2z"/>',
  calendar:
    '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16"/><path d="M8.5 3.5v4M15.5 3.5v4"/>',
  message:
    '<path d="M5.5 18.5 4 21l3.2-1.2A8.5 8.5 0 1 0 4 12.5a8.4 8.4 0 0 0 1.5 6z"/><path d="M8.5 10.5h7M8.5 14h4.5"/>',
  route:
    '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h7.5a3 3 0 0 0 0-6h-7a3 3 0 0 1 0-6H16"/>',
  hourglass:
    '<path d="M7 3.5h10M7 20.5h10"/><path d="M8 3.5c0 4 4 5 4 8.5s-4 4.5-4 8.5"/><path d="M16 3.5c0 4-4 5-4 8.5s4 4.5 4 8.5"/>',
  keyboard:
    '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M10.5 10h.01M14 10h.01M17.5 10h.01M7 14h10"/>',
  memory:
    '<rect x="3.5" y="7" width="17" height="10" rx="1.5"/><path d="M7.5 10.5v3M11 10.5v3M14.5 10.5v3"/><path d="M6.5 17v2.5M12 17v2.5M17.5 17v2.5"/>',
  eye: '<path d="M2.8 12S6 5.5 12 5.5 21.2 12 21.2 12 18 18.5 12 18.5 2.8 12 2.8 12z"/><circle cx="12" cy="12" r="3"/>',
  dot: '<circle cx="12" cy="12" r="4" fill="currentColor"/>',
  minus: '<path d="M6 12h12"/>',
  plus: '<path d="M12 6v12M6 12h12"/>',
};

const BRAND_MARK =
  '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><rect width="32" height="32" rx="7" fill="#171717"/><path d="M9 17l5 5 9-11" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/** The markup of one icon, decorative unless a label is given (then it is an image). */
export function iconMarkup(name, { label = "", size = 20 } = {}) {
  const body = PATHS[name] ?? PATHS.dot;
  const a11y = label
    ? `role="img" aria-label="${label.replace(/"/g, "&quot;")}"`
    : 'aria-hidden="true" focusable="false"';
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" ${a11y}>${body}</svg>`;
}

/** One icon as an element. */
export function icon(name, options = {}) {
  const holder = document.createElement("span");
  holder.className = "icon-box";
  holder.innerHTML = iconMarkup(name, options);
  return holder.firstElementChild;
}

/** The ComplianceWatch mark (the web app's icon.svg): a dark square with a tick. */
export function brandMark() {
  const holder = document.createElement("span");
  holder.className = "brand-mark";
  holder.innerHTML = BRAND_MARK;
  return holder;
}

export const ICON_NAMES = Object.keys(PATHS);
