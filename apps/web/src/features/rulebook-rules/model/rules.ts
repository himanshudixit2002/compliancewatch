import type { RuleSummary } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { withQuery } from "@/shared/lib/url";
import type { RuleRow } from "../ui/rules-shared";

/**
 * The rule list's rows: every rule by key, with its regulator, the title of its latest version
 * (the rulebook leaves out a rule whose only drafts are closed) and a link to all its versions.
 */
export function ruleRows(rules: readonly RuleSummary[]): RuleRow[] {
  const versions = hrefFor(screenById("admin.rulebook.versions"));
  return (
    [...rules]
      // By key in code point order, the order the rulebook pages rules in.
      .sort((a, b) => (a.ruleKey < b.ruleKey ? -1 : a.ruleKey > b.ruleKey ? 1 : 0))
      .map((rule) => ({
        ruleKey: rule.ruleKey,
        ruleId: rule.ruleId,
        regulator: rule.regulator,
        title: rule.title,
        versionsHref: withQuery(versions, { status: "all", rule: rule.ruleKey }),
      }))
  );
}
