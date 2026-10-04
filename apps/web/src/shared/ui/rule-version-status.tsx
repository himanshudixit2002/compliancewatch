import { StatusChip, humaniseStatus } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * A rule version's status and its seed review status as chips whose text, not their colour, says
 * what they are. The statuses are the rulebook's (draft, in_review, approved, published,
 * superseded, withdrawn); one the app does not know yet is shown humanised in the neutral tone.
 */
const STATUSES: Readonly<Record<string, { key: MessageKey; tone: Tone }>> = {
  draft: { key: "ruleVersion.status.draft", tone: "neutral" },
  in_review: { key: "ruleVersion.status.in_review", tone: "info" },
  approved: { key: "ruleVersion.status.approved", tone: "info" },
  published: { key: "ruleVersion.status.published", tone: "success" },
  superseded: { key: "ruleVersion.status.superseded", tone: "neutral" },
  withdrawn: { key: "ruleVersion.status.withdrawn", tone: "danger" },
};

const SEED_STATUSES: Readonly<Record<string, { key: MessageKey; tone: Tone }>> = {
  needs_review: { key: "ruleVersion.seed.needs_review", tone: "warning" },
  reviewed: { key: "ruleVersion.seed.reviewed", tone: "success" },
};

/** The words for a rule version status ("In review"), or the status humanised. */
export function ruleVersionStatusLabel(status: string): string {
  const known = STATUSES[status];
  return known === undefined ? humaniseStatus(status) : t(known.key);
}

export interface RuleVersionStatusChipProps {
  status: string;
  className?: string;
}

export function RuleVersionStatusChip({ status, className }: RuleVersionStatusChipProps) {
  return (
    <StatusChip
      status={status}
      tone={STATUSES[status]?.tone ?? "neutral"}
      label={ruleVersionStatusLabel(status)}
      className={className}
    />
  );
}

export interface SeedStatusChipProps {
  seedStatus: string;
  className?: string;
}

/** "Not yet reviewed" until an analyst's approval completes a review round, then "Reviewed". */
export function SeedStatusChip({ seedStatus, className }: SeedStatusChipProps) {
  const known = SEED_STATUSES[seedStatus];
  return (
    <StatusChip
      status={seedStatus}
      tone={known?.tone ?? "neutral"}
      label={known === undefined ? humaniseStatus(seedStatus) : t(known.key)}
      className={className}
    />
  );
}
