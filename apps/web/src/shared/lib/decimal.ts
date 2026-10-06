/**
 * Money as decimal strings, never floats. Services send amounts as strings with two decimals
 * ("1499.00") or as integer paise; this module converts between them with bigint arithmetic.
 */
const DECIMAL = /^(-)?(\d+)(?:\.(\d{1,2}))?$/;

/** "1499.5" -> 149950n; more than two decimals or a malformed string throws. */
export function toPaise(amount: string): bigint {
  const match = DECIMAL.exec(amount.trim());
  if (match === null) throw new Error(`not a money amount: ${amount}`);
  const [, sign, whole, fraction = ""] = match;
  const paise = BigInt(whole as string) * 100n + BigInt(fraction.padEnd(2, "0"));
  return sign === "-" ? -paise : paise;
}

/** 149950n -> "1499.50". */
export function fromPaise(paise: bigint | number): string {
  const value = BigInt(paise);
  const sign = value < 0n ? "-" : "";
  const abs = value < 0n ? -value : value;
  const whole = abs / 100n;
  const fraction = (abs % 100n).toString().padStart(2, "0");
  return `${sign}${whole}.${fraction}`;
}

export function addAmounts(a: string, b: string): string {
  return fromPaise(toPaise(a) + toPaise(b));
}

export function subtractAmounts(a: string, b: string): string {
  return fromPaise(toPaise(a) - toPaise(b));
}

/** -1, 0 or 1. */
export function compareAmounts(a: string, b: string): -1 | 0 | 1 {
  const x = toPaise(a);
  const y = toPaise(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

export function isAmount(value: string): boolean {
  return DECIMAL.test(value.trim());
}

/** Decimal text of any precision: "0.0012", "20000", "-3.5". */
const DECIMAL_TEXT = /^(-)?(\d+)(?:\.(\d+))?$/;

export function isDecimalText(value: string): boolean {
  return DECIMAL_TEXT.test(value.trim());
}

/**
 * A share written as decimal text ("0.061700") as a percentage with `places` decimals, rounded
 * half up with bigint arithmetic: "0.061700" is "6.17", "0.000060" is "0.01", "1.2" is "120.00".
 * Malformed text throws.
 */
export function ratioPercent(ratio: string, places = 2): string {
  const match = DECIMAL_TEXT.exec(ratio.trim());
  if (match === null) throw new Error(`not a decimal: ${ratio}`);
  const [, sign, whole, fraction = ""] = match;
  // The ratio in units of 10^-(places + 2), with one more digit to round on.
  const digits = places + 3;
  const scaled = BigInt(`${whole}${fraction.padEnd(digits, "0").slice(0, digits)}`);
  const rounded = (scaled + 5n) / 10n;
  const factor = 10n ** BigInt(places);
  const integer = rounded / factor;
  const rest = (rounded % factor).toString().padStart(places, "0");
  const negative = sign === "-" && rounded !== 0n;
  return `${negative ? "-" : ""}${integer}${places > 0 ? `.${rest}` : ""}`;
}
