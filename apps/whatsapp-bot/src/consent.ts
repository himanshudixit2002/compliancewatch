/**
 * Keywords a person types to opt out, opt in or ask for help, in English, Hindi and the usual
 * Hinglish spellings. Matching is on the whole message after trimming and dropping
 * punctuation, so "Stop." and "STOP" agree and "please stop sending" does not (a reply, not a
 * command; the conversation handles it as a question).
 */
export type Intent = "opt_out" | "opt_in" | "help" | "message";

const OPT_OUT = new Set([
  "STOP",
  "UNSUBSCRIBE",
  "CANCEL",
  "END",
  "QUIT",
  "BAND",
  "BAND KARO",
  "BANDH",
  "रोकें",
  "रोको",
  "बंद",
  "बंद करो",
]);
const OPT_IN = new Set([
  "START",
  "JOIN",
  "SUBSCRIBE",
  "YES",
  "HAAN",
  "HAN",
  "SHURU",
  "SHURU KARO",
  "हाँ",
  "हां",
  "शुरू",
  "शुरू करो",
]);
const HELP = new Set(["HELP", "MADAD", "मदद", "SAHAYATA", "सहायता"]);

const PUNCTUATION = /[.!?,;:'"()।]+/g;
const DEVANAGARI = /[ऀ-ॿ]/;

export function normaliseKeyword(text: string): string {
  return text.replace(PUNCTUATION, " ").replace(/\s+/g, " ").trim().toUpperCase();
}

export function detectIntent(text: string | null): Intent {
  if (text === null) return "message";
  const keyword = normaliseKeyword(text);
  if (OPT_OUT.has(keyword)) return "opt_out";
  if (OPT_IN.has(keyword)) return "opt_in";
  if (HELP.has(keyword)) return "help";
  return "message";
}

/** "hi" when the message is written in Devanagari, otherwise "en". */
export function detectLanguage(text: string | null): "en" | "hi" {
  return text !== null && DEVANAGARI.test(text) ? "hi" : "en";
}
