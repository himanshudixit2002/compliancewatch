import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import en from "./messages/en.json";
import {
  DEFAULT_LOCALE,
  createTranslator,
  createTranslatorFrom,
  interpolate,
  isLocale,
  isMessageKey,
  messages,
  t,
} from "./index";

const SRC = resolve(__dirname, "..", "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

/**
 * Message families a module picks by value with a template literal, such as
 * t(`status.${status}`), so no literal names their keys. Each names the module that builds the
 * key and what the value is. A key outside these families needs a literal reference; a key
 * inside one must also match a template literal in src, so a family keeps no key nothing builds.
 */
const DYNAMIC_PREFIXES: Readonly<Record<string, string>> = {
  "attribute.source.": "features/business/model/attributes.ts: where a stored value came from",
  "attribute.state.": "features/business/model/values.ts: the state of a stored value",
  "billing.period.": "features/billing/model/plans.ts: a plan's period (else the raw period)",
  "business.level.": "features/business/model/business-pages.ts: the level of a profile node",
  "consent.checkbox.": "features/consents/model/purposes.ts: the box of a consent purpose",
  "consent.purpose.": "features/consents and notification-preferences: a consent purpose",
  "consent.source.": "features/consents and notification-preferences: where a record came from",
  "consentSettings.status.": "features/consents/ui/consent-settings.tsx: a purpose's state",
  "design.theme.": "features/design-catalogue/ui/theme-toggle.tsx: a theme option",
  "directory.clients.": "features/business/ui/business-directory.tsx: the CA firm's list",
  "directory.owner.": "features/business/ui/business-directory.tsx: the owner's list",
  "nav.status.": "shared/ui/internal-shell.tsx: the status hint of a tool not built",
  "notifications.another.": "features/notification-preferences/ui: per channel",
  "notifications.recipient.": "features/notification-preferences/model/channels.ts: per channel",
  "notifications.recipientHelp.": "features/notification-preferences/ui: per channel",
  "onboarding.step.": "shared/ui/onboarding-stepper.tsx: an onboarding step",
  "reviewTask.reason.": "features/business/model/review-tasks.ts: why a review task opened",
  "settings.about.": "features/settings/model/cards.ts: a settings page's sentence, by screen id",
  "sitemap.kind.": "features/sitemap and admin-home: the kind of a registry entry",
  "sitemap.section.": "features/sitemap/ui/sitemap-view.tsx: a registry section",
  "status.": "shared/ui/screen-status-chip.tsx: a registry status",
};

/** The text of every source file in src, tests included. */
function allSources(): string {
  return sourceFiles(SRC)
    .map((file) => readFileSync(file, "utf8"))
    .join("\n");
}

/** Whether the key is written out as a string anywhere in src. */
function isLiteral(sources: string, key: string): boolean {
  return [`"${key}"`, `'${key}'`, `\`${key}\``].some((quoted) => sources.includes(quoted));
}

/** Each template literal in the app's code that builds a message key, as a pattern. */
function keyTemplates(): RegExp[] {
  const patterns: RegExp[] = [];
  for (const file of sourceFiles(SRC).filter((path) => !/\.test\.tsx?$/.test(path))) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(/`([a-z][a-zA-Z0-9]*\.[^`]*?\$\{[^`]*)`/g)) {
      const parts = (match[1] as string).split(/\$\{[^}]*\}/);
      const escaped = parts.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
      patterns.push(new RegExp(`^${escaped.join("[A-Za-z0-9_.]+")}$`));
    }
  }
  return patterns;
}

describe("messages", () => {
  it("are flat, namespaced, non-empty English strings", () => {
    const keys = Object.keys(en);
    expect(keys.length).toBeGreaterThan(50);
    for (const key of keys) {
      expect(key).toMatch(/^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9_]+)+$/);
      expect(en[key as keyof typeof en].trim().length, key).toBeGreaterThan(0);
    }
    expect(messages).toBe(en);
  });

  it("cover every t() literal used in src", () => {
    const missing: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/\bt\(\s*["']([^"']+)["']/g)) {
        const key = match[1] as string;
        if (!isMessageKey(key)) missing.push(`${file}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("are each referenced in src, as a literal or as a member of a dynamic family", () => {
    const sources = allSources();
    const templates = keyTemplates();
    const prefixes = Object.keys(DYNAMIC_PREFIXES);
    const unreferenced = Object.keys(en).filter(
      (key) =>
        !isLiteral(sources, key) &&
        !(
          prefixes.some((prefix) => key.startsWith(prefix)) &&
          templates.some((pattern) => pattern.test(key))
        ),
    );
    expect(unreferenced, "remove the key, or reference it").toEqual([]);
  });

  it("list only dynamic families that a template literal builds and a key needs", () => {
    const sources = allSources();
    const templates = keyTemplates();
    for (const [prefix, reason] of Object.entries(DYNAMIC_PREFIXES)) {
      expect(reason.trim().length, prefix).toBeGreaterThan(0);
      const needed = Object.keys(en).filter(
        (key) =>
          key.startsWith(prefix) &&
          !isLiteral(sources, key) &&
          templates.some((pattern) => pattern.test(key)),
      );
      expect(needed.length, `${prefix} covers no key that only a template builds`).toBeGreaterThan(
        0,
      );
    }
  });

  it("keep any Hindi file inside the English key set", () => {
    const hiPath = join(__dirname, "messages", "hi.json");
    if (!existsSync(hiPath)) return;
    const hi = JSON.parse(readFileSync(hiPath, "utf8")) as Record<string, string>;
    const extra = Object.keys(hi).filter((key) => !isMessageKey(key));
    expect(extra).toEqual([]);
  });
});

describe("t", () => {
  it("returns the English message and interpolates variables", () => {
    expect(t("common.appName")).toBe("ComplianceWatch");
    expect(t("common.version", { version: "0.1-draft" })).toBe("Version 0.1-draft");
    expect(t("date.inDays", { count: 3 })).toBe("in 3 days");
  });

  it("leaves an unknown placeholder as written and ignores extra variables", () => {
    expect(interpolate("Hello {name}", {})).toBe("Hello {name}");
    expect(interpolate("Hello {name}", { name: "Example person", other: 1 })).toBe(
      "Hello Example person",
    );
    expect(interpolate("No placeholders")).toBe("No placeholders");
  });

  it("falls back key by key from a partial locale", () => {
    const hi = createTranslatorFrom({ "common.back": "Wapas" });
    expect(hi("common.back")).toBe("Wapas");
    expect(hi("common.home")).toBe(en["common.home"]);
    expect(createTranslator("hi")("common.home")).toBe(en["common.home"]);
    expect(createTranslator("en")("common.home")).toBe(en["common.home"]);
  });

  it("knows its locales and keys", () => {
    expect(DEFAULT_LOCALE).toBe("en");
    expect(isLocale("hi")).toBe(true);
    expect(isLocale("fr")).toBe(false);
    expect(isMessageKey("common.home")).toBe(true);
    expect(isMessageKey("nope.nope")).toBe(false);
  });
});
