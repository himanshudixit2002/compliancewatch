import "server-only";

import type { AttributeValue, Attributes, SpanStatus } from "@opentelemetry/api";
import type { ReadableSpan, Span, SpanProcessor } from "@opentelemetry/sdk-trace-base";

/**
 * Keeps personal data out of every span the web server exports (D-057). The addresses it calls
 * carry some: a notification preference is keyed by its address
 * (`/v1/notification/preferences/{channel}/{recipient}`, a WhatsApp number or an email), and the
 * business search sends what was typed (`GET /v1/businesses?q=`, a name, a PAN or a GSTIN). The
 * fetch instrumentation of @vercel/otel names each call `fetch GET <full URL>` and copies the URL
 * into `http.url` and `resource.name`, and Next.js puts the request's path and query in
 * `http.target`. So every string in a span (its name, its attributes, its events' and links'
 * attributes, its status message) is rewritten:
 *
 *   - in every URL and absolute path, the query and the fragment are dropped, and a user and
 *     password before the host; `url.query`, which holds a query alone, is emptied;
 *   - the segment of a known route that names a person becomes its placeholder, whatever it holds
 *     (`/v1/notification/preferences/whatsapp/{recipient}`);
 *   - any other path segment that is an email, a phone number, a PAN or a GSTIN becomes `{email}`,
 *     `{phone}`, `{pan}` or `{gstin}`, and so does one standing anywhere else in the text;
 *   - everything else stays, so a route still reads as a route and an id as an id.
 *
 * `RedactingSpanProcessor` runs ahead of the exporting processors: at the start through the span's
 * own API, and again at the end on the finished record the exporter reads, for a name or an
 * attribute set after the start (Next.js names its request span by its route late, and @vercel/otel
 * adds `resource.name` when a span ends).
 */
export const PLACEHOLDERS = {
  recipient: "{recipient}",
  email: "{email}",
  phone: "{phone}",
  pan: "{pan}",
  gstin: "{gstin}",
} as const;

/**
 * Routes with a segment that names a person whatever it holds. A braced segment is replaced by
 * itself (the placeholder); `*` matches any one segment and stays. The notification preference
 * route is read by the preferences page and written by the consents page.
 */
export const PERSONAL_ROUTES: readonly string[] = ["/v1/notification/preferences/*/{recipient}"];

/** Attributes that hold a query alone: emptied, whatever the query holds. */
const QUERY_ATTRIBUTES: ReadonlySet<string> = new Set(["url.query"]);

const TEMPLATES: readonly (readonly string[])[] = PERSONAL_ROUTES.map((route) =>
  route.split("/").filter((segment) => segment !== ""),
);

const EMAIL = /^[^\s@/]+@[^\s@/]+\.[^\s@/]+$/;
/** A phone number: 10 to 15 digits, or "+" and the digits with spaces or hyphens between them. */
const PHONE_DIGITS = /^\d{10,15}$/;
const PHONE_INTERNATIONAL = /^\+\d[\d -]*\d$/;
const PAN = /^[A-Z]{5}\d{4}[A-Z]$/i;
const GSTIN = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[\dA-Z]$/i;

/** The placeholder for a value that is an email, a phone number, a PAN or a GSTIN; else null. */
export function personalPlaceholder(value: string): string | null {
  const text = value.trim();
  if (EMAIL.test(text)) return PLACEHOLDERS.email;
  if (GSTIN.test(text)) return PLACEHOLDERS.gstin;
  if (PAN.test(text)) return PLACEHOLDERS.pan;
  if (PHONE_DIGITS.test(text)) return PLACEHOLDERS.phone;
  if (PHONE_INTERNATIONAL.test(text) && PHONE_DIGITS.test(text.replace(/[+ -]/g, ""))) {
    return PLACEHOLDERS.phone;
  }
  return null;
}

/**
 * The same values standing inside a text ("for owner@example.com:", "q=ABCDE1234F"), each bounded
 * so that it is never cut out of a longer word: a digit run inside an id (the last group of a
 * UUID, a hash) is no phone number. A PAN or a GSTIN inside a text is matched in capitals only,
 * as both are written, so a lower-case file or chunk name is left alone.
 */
const EMBEDDED: readonly (readonly [RegExp, string])[] = [
  [/(?<![\w.+-])[\w.+-]+@[a-z\d-]+(?:\.[a-z\d-]+)*\.[a-z]{2,}(?![\w-])/gi, PLACEHOLDERS.email],
  [/(?<![\dA-Za-z])\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[\dA-Z](?![\dA-Za-z])/g, PLACEHOLDERS.gstin],
  [/(?<![\dA-Za-z])[A-Z]{5}\d{4}[A-Z](?![\dA-Za-z])/g, PLACEHOLDERS.pan],
  [/(?<![\w+-])\+\d(?:[ -]?\d){9,14}(?![\w-])/g, PLACEHOLDERS.phone],
  [/(?<![\w+-])\d{10,15}(?![\w-])/g, PLACEHOLDERS.phone],
];

function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** Replaces the braced segments of every known route the path holds, wherever it starts. */
function markRoutes(segments: readonly string[], out: string[]): void {
  for (const template of TEMPLATES) {
    for (let start = 0; start + template.length <= segments.length; start += 1) {
      const matches = template.every(
        (part, index) => part === "*" || part.startsWith("{") || part === segments[start + index],
      );
      if (!matches) continue;
      template.forEach((part, index) => {
        if (part.startsWith("{")) out[start + index] = part;
      });
    }
  }
}

/** A path with its personal segments replaced; the query must already be gone. */
export function redactPath(path: string): string {
  const segments = path.split("/");
  const out = segments.map((segment) =>
    segment === "" ? segment : (personalPlaceholder(decodeSegment(segment)) ?? segment),
  );
  markRoutes(segments, out);
  return out.join("/");
}

const SCHEME_AND_AUTHORITY = /^([a-z][a-z\d+.-]*:\/\/)([^/]*)/i;

/** One URL or path: no query, no fragment, no user or password, no personal segment. */
export function redactUrl(value: string): string {
  const cut = value.search(/[?#]/);
  const bare = cut === -1 ? value : value.slice(0, cut);
  const head = SCHEME_AND_AUTHORITY.exec(bare);
  if (head === null) return redactPath(bare);
  const scheme = head[1] ?? "";
  const authority = head[2] ?? "";
  const host = authority.slice(authority.lastIndexOf("@") + 1);
  return `${scheme}${host}${redactPath(bare.slice(head[0].length))}`;
}

/**
 * Every URL (any scheme) and every absolute path in a text, the way a span name or a message holds
 * them: "fetch GET http://...", "GET /businesses?q=...". A slash inside a word ("and/or", a date)
 * starts no path.
 */
const URLS_AND_PATHS = /[a-z][a-z\d+.-]*:\/\/[^\s"'<>`]*|(?<![\w.:/~%-])\/[^\s"'<>`]*/gi;

/** A span name or an attribute's text with its URLs redacted and no person's value left in it. */
export function redactText(text: string): string {
  let redacted = text.replace(URLS_AND_PATHS, (match) => redactUrl(match));
  for (const [pattern, placeholder] of EMBEDDED) {
    redacted = redacted.replace(pattern, placeholder);
  }
  return redacted;
}

/** The value redacted, or the same value when nothing in it changes. */
export function redactValue(value: AttributeValue | undefined): AttributeValue | undefined {
  if (typeof value === "string") return redactText(value);
  if (!Array.isArray(value)) return value;
  let changed = false;
  const items = (value as readonly unknown[]).map((item) => {
    if (typeof item !== "string") return item;
    const next = redactText(item);
    changed ||= next !== item;
    return next;
  });
  return changed ? (items as AttributeValue) : value;
}

/** One attribute redacted by its key and its value. */
export function redactAttribute(
  key: string,
  value: AttributeValue | undefined,
): AttributeValue | undefined {
  if (QUERY_ATTRIBUTES.has(key) && typeof value === "string" && value !== "") return "";
  return redactValue(value);
}

/** Rewrites a finished record's attributes in place. */
function redactRecord(attributes: Attributes): void {
  for (const [key, value] of Object.entries(attributes)) {
    const next = redactAttribute(key, value);
    if (next !== value) attributes[key] = next;
  }
}

/**
 * Installed first among @vercel/otel's span processors, so the exporting ones read the span after
 * it. A span that has ended takes no change through its API, so the end rewrites the record the
 * exporter reads later (the batch processor keeps the span itself until it exports).
 */
export class RedactingSpanProcessor implements SpanProcessor {
  onStart(span: Span): void {
    const name = redactText(span.name);
    if (name !== span.name) span.updateName(name);
    for (const [key, value] of Object.entries(span.attributes)) {
      const next = redactAttribute(key, value);
      if (next !== value && next !== undefined) span.setAttribute(key, next);
    }
  }

  onEnd(span: ReadableSpan): void {
    const record = span as { name: string; status: SpanStatus };
    record.name = redactText(span.name);
    redactRecord(span.attributes);
    for (const event of span.events) {
      if (event.attributes !== undefined) redactRecord(event.attributes);
    }
    for (const link of span.links) {
      if (link.attributes !== undefined) redactRecord(link.attributes);
    }
    if (span.status.message !== undefined) {
      record.status = { ...span.status, message: redactText(span.status.message) };
    }
  }

  forceFlush(): Promise<void> {
    return Promise.resolve();
  }

  shutdown(): Promise<void> {
    return Promise.resolve();
  }
}
