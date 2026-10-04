/**
 * Language names for the codes the services use ("hi" is "Hindi"), in English, from the
 * platform's own names (Intl.DisplayNames) rather than app wording. A code the platform does not
 * name, or one that is not a language code at all, is shown as written.
 */
export const DEFAULT_LANGUAGE = "en";

const names = new Intl.DisplayNames(["en"], { type: "language", fallback: "none" });

export function languageName(code: string): string {
  try {
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

export interface LanguageOption {
  value: string;
  label: string;
}

/** The codes as options, each once: English first, then by name. */
export function languageOptions(codes: Iterable<string>): LanguageOption[] {
  return [...new Set(codes)]
    .map((code) => ({ value: code, label: languageName(code) }))
    .sort((a, b) =>
      a.value === DEFAULT_LANGUAGE
        ? -1
        : b.value === DEFAULT_LANGUAGE
          ? 1
          : a.label.localeCompare(b.label, "en"),
    );
}
