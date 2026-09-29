import en from "./messages/en.json";

/**
 * Typed message lookup with `{name}` interpolation. English is the source of truth
 * (messages/en.json, flat keys namespaced by feature); another locale supplies a partial file
 * and falls back key by key. No framework: pages call t() in server and client components.
 */
export type MessageKey = keyof typeof en;
export type Messages = Readonly<Record<MessageKey, string>>;
export type Locale = "en" | "hi";
export type Vars = Readonly<Record<string, string | number>>;
export type Translator = (key: MessageKey, vars?: Vars) => string;

export const DEFAULT_LOCALE: Locale = "en";
export const LOCALES: readonly Locale[] = ["en", "hi"];

/** Partial locale files register here; hi.json joins when the Hindi wording exists. */
const OVERRIDES: Readonly<Record<Locale, Partial<Messages>>> = { en: {}, hi: {} };

export const messages: Messages = en;

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export function isMessageKey(value: string): value is MessageKey {
  return Object.hasOwn(en, value);
}

/** Replaces `{name}` with vars.name; an unknown placeholder is left as written. */
export function interpolate(template: string, vars?: Vars): string {
  if (vars === undefined) return template;
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/** A translator over an explicit override map, falling back to English key by key. */
export function createTranslatorFrom(overrides: Partial<Messages>): Translator {
  return (key, vars) => interpolate(overrides[key] ?? en[key], vars);
}

export function createTranslator(locale: Locale): Translator {
  return createTranslatorFrom(OVERRIDES[locale]);
}

/** The default (English) translator. */
export const t: Translator = createTranslatorFrom(OVERRIDES.en);
