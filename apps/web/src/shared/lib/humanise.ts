/**
 * Enum values from services (snake_case or kebab-case) read as sentences, with the spellings
 * that must stay upper-case. Regulatory wording itself comes from service data or the ontology,
 * never from here.
 */
const SPELLINGS: Readonly<Record<string, string>> = {
  qrmp: "QRMP",
  gstin: "GSTIN",
  gst: "GST",
  gstr: "GSTR",
  hsn: "HSN",
  sac: "SAC",
  sez: "SEZ",
  llp: "LLP",
  huf: "HUF",
  isd: "ISD",
  tds: "TDS",
  tcs: "TCS",
  pan: "PAN",
  ca: "CA",
  fy: "FY",
  id: "ID",
  api: "API",
  llm: "LLM",
  otp: "OTP",
  mfa: "MFA",
  sso: "SSO",
  pdf: "PDF",
  url: "URL",
  whatsapp: "WhatsApp",
};

function word(token: string, first: boolean): string {
  const lower = token.toLowerCase();
  const spelling = SPELLINGS[lower];
  if (spelling !== undefined) return spelling;
  return first ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
}

/** "not_started" -> "Not started"; "gstr3b_monthly" -> "Gstr3b monthly"; "ca_admin" -> "CA admin". */
export function humanise(value: string): string {
  const tokens = value
    .trim()
    .split(/[_\-\s]+/)
    .filter((token) => token.length > 0);
  return tokens.map((token, index) => word(token, index === 0)).join(" ");
}

/** Every word capitalised where a sentence would not be: "ca_admin" -> "CA Admin". */
export function titleCase(value: string): string {
  return humanise(value)
    .split(" ")
    .map((token) =>
      token === token.toLowerCase() ? token.charAt(0).toUpperCase() + token.slice(1) : token,
    )
    .join(" ");
}

export function isKnownSpelling(token: string): boolean {
  return Object.hasOwn(SPELLINGS, token.toLowerCase());
}
