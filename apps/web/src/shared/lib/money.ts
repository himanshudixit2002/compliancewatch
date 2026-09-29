import { fromPaise, toPaise } from "./decimal.ts";

/**
 * Rupee amounts for display: "Rs 1,499.00" with en-IN grouping (lakhs and crores). Amounts
 * arrive as integer paise or as decimal strings; nothing here does float arithmetic.
 */
const rupees = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const CURRENCY_PREFIX = "Rs ";

/** 149900 -> "Rs 1,499.00"; -100 -> "-Rs 1.00". */
export function formatPaise(paise: bigint | number): string {
  const value = BigInt(paise);
  const abs = value < 0n ? -value : value;
  const sign = value < 0n ? "-" : "";
  const whole = abs / 100n;
  const fraction = Number(abs % 100n) / 100;
  // Group the whole part as a bigint-safe number; amounts above 2^53 paise are not a product case.
  const text = rupees.format(Number(whole) + fraction);
  return `${sign}${CURRENCY_PREFIX}${text}`;
}

/** "1499.00" -> "Rs 1,499.00". */
export function formatAmount(amount: string): string {
  return formatPaise(toPaise(amount));
}

/** Paise as the decimal string a service expects: 149950 -> "1499.50". */
export function paiseToAmount(paise: bigint | number): string {
  return fromPaise(paise);
}
