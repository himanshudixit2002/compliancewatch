/** One rule as the list shows it; in the ui directory so the client table may import it. */
export interface RuleRow {
  ruleKey: string;
  ruleId: string;
  regulator: string;
  title: string;
  /** Every version of the rule, on the rule version list. */
  versionsHref: string;
}

/** The rows whose key, title or regulator holds every word typed, in any case. */
export function filterRules(rows: readonly RuleRow[], query: string): RuleRow[] {
  const words = query
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word !== "");
  if (words.length === 0) return [...rows];
  return rows.filter((row) => {
    const text = `${row.ruleKey} ${row.title} ${row.regulator}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}
