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
    expect(interpolate("Hello {name}", { name: "Asha", other: 1 })).toBe("Hello Asha");
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
