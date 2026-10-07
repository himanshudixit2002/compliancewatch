import type { ReviewStats } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { percent } from "./queue";

/**
 * The review queue in numbers, as `GET /v1/rulebook/review/stats` counts it: the tasks by status
 * and by regulator, the decisions, the rule candidates analysts decided and the acceptance rate
 * (ADR-006's measure of the extraction: the share of decided candidates approved without an
 * edit), the median time from a task's opening to its decision and how long the oldest open task
 * has waited. Nothing is computed here but the words: every count is the rulebook's.
 */
const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** A length of time in words, to the minute: "3 h 20 min", "2 d 4 h", "Less than a minute". */
export function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < MINUTE) return t("reviewStats.duration.underMinute");
  if (whole < HOUR)
    return t("reviewStats.duration.minutes", { minutes: Math.floor(whole / MINUTE) });
  if (whole < DAY) {
    return t("reviewStats.duration.hours", {
      hours: Math.floor(whole / HOUR),
      minutes: Math.floor((whole % HOUR) / MINUTE),
    });
  }
  return t("reviewStats.duration.days", {
    days: Math.floor(whole / DAY),
    hours: Math.floor((whole % DAY) / HOUR),
  });
}

/** The acceptance rate as a percentage, or why there is none. */
export function acceptanceText(rate: number | null): string {
  return rate === null ? t("reviewStats.acceptanceNone") : percent(rate);
}

/** How long the oldest open task has waited, or that none waits. */
export function oldestText(
  stats: Pick<ReviewStats, "oldestOpenAt" | "oldestOpenAgeSeconds">,
): string {
  return stats.oldestOpenAt === null
    ? t("reviewStats.oldestNone")
    : formatDuration(stats.oldestOpenAgeSeconds);
}

export interface StatsStrip {
  open: number;
  claimed: number;
  decided: number;
  acceptance: string;
  oldest: string;
  statsHref: string;
}

/** The queue's strip: the counts, the acceptance rate and the oldest wait, with the full page. */
export function statsStrip(stats: ReviewStats): StatsStrip {
  return {
    open: stats.byStatus.open,
    claimed: stats.byStatus.claimed,
    decided: stats.byStatus.decided,
    acceptance: acceptanceText(stats.candidates.acceptanceRate),
    oldest: oldestText(stats),
    statsHref: hrefFor(screenById("admin.review.stats")),
  };
}

export interface RegulatorRow {
  regulator: string;
  open: number;
  claimed: number;
  decided: number;
  total: number;
}

export interface StatsView {
  byStatus: { open: number; claimed: number; decided: number; total: number };
  regulators: RegulatorRow[];
  decisions: { approved: number; returned: number; rejected: number; total: number };
  candidates: {
    decided: number;
    approved: number;
    approvedWithoutEdits: number;
    rejected: number;
    acceptance: string;
    /** "1 of the 3 decided candidates was approved without an edit."; null while none is. */
    explained: string | null;
  };
  median: string;
  oldest: string;
  /** When the oldest open task opened; null when none waits. */
  oldestSince: string | null;
}

export function statsView(stats: ReviewStats): StatsView {
  const { open, claimed, decided } = stats.byStatus;
  const { approved, returned, rejected } = stats.decisions;
  const candidates = stats.candidates;
  return {
    byStatus: { open, claimed, decided, total: open + claimed + decided },
    regulators: stats.byRegulator.map((row) => ({
      ...row,
      total: row.open + row.claimed + row.decided,
    })),
    decisions: { approved, returned, rejected, total: approved + returned + rejected },
    candidates: {
      decided: candidates.decided,
      approved: candidates.approved,
      approvedWithoutEdits: candidates.approvedWithoutEdits,
      rejected: candidates.rejected,
      acceptance: acceptanceText(candidates.acceptanceRate),
      explained:
        candidates.acceptanceRate === null
          ? null
          : t("reviewStats.acceptanceExplained", {
              unedited: candidates.approvedWithoutEdits,
              decided: candidates.decided,
            }),
    },
    median:
      stats.medianSecondsToDecide === null
        ? t("reviewStats.medianNone")
        : formatDuration(stats.medianSecondsToDecide),
    oldest: oldestText(stats),
    oldestSince: stats.oldestOpenAt === null ? null : formatDateTime(stats.oldestOpenAt),
  };
}
