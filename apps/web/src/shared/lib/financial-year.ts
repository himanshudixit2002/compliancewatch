import { isDateKey, todayKey } from "./dates.ts";

/**
 * Indian financial years run from 1 April to 31 March and are labelled by their start year
 * and the last two digits of the end year: "2026-27".
 */
export interface FinancialYear {
  /** The calendar year the financial year starts in. */
  start: number;
}

const LABEL = /^(\d{4})-(\d{2})$/;

export function financialYearOf(dateKey: string): FinancialYear {
  if (!isDateKey(dateKey)) throw new Error(`not a date: ${dateKey}`);
  const [year, month] = dateKey.split("-").map(Number) as [number, number];
  return { start: month >= 4 ? year : year - 1 };
}

export function currentFinancialYear(now: Date = new Date()): FinancialYear {
  return financialYearOf(todayKey(now));
}

export function financialYearLabel(fy: FinancialYear): string {
  const end = (fy.start + 1) % 100;
  return `${fy.start}-${end.toString().padStart(2, "0")}`;
}

/** "2026-27" -> { start: 2026 }; null for anything else, including a wrong end year. */
export function parseFinancialYearLabel(label: string): FinancialYear | null {
  const match = LABEL.exec(label);
  if (match === null) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  if ((start + 1) % 100 !== end) return null;
  return { start };
}

export function financialYearRange(fy: FinancialYear): { from: string; to: string } {
  return { from: `${fy.start}-04-01`, to: `${fy.start + 1}-03-31` };
}

export function nextFinancialYear(fy: FinancialYear): FinancialYear {
  return { start: fy.start + 1 };
}

export function previousFinancialYear(fy: FinancialYear): FinancialYear {
  return { start: fy.start - 1 };
}
