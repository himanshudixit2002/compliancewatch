import type { Tone } from "@compliancewatch/ui";
import type { FanOutHold, FanOutRun, FanOutStatus } from "@/entities/applicability/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import { LOCALE, formatDateTime } from "@/shared/lib/dates";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { levelLabel } from "@/shared/ui/applicability";
import type { FanOutControl, HoldView } from "../ui/controls-shared";

export type { FanOutControl, HoldView } from "../ui/controls-shared";

/**
 * The fan-out screens' words: a run's status, how far it got, its flips against the version it
 * supersedes, who changed it last and why, which controls its status allows, and the global hold.
 * Everything comes from the engine's run and hold; the version's number and title come from the
 * rulebook, read for the purpose.
 */
export const FAN_OUT_PAGE_SIZE = 25;

const STATUS: Readonly<Record<FanOutStatus, { key: MessageKey; tone: Tone }>> = {
  running: { key: "fanOuts.status.running", tone: "info" },
  held: { key: "fanOuts.status.held", tone: "warning" },
  paused: { key: "fanOuts.status.paused", tone: "warning" },
  completed: { key: "fanOuts.status.completed", tone: "success" },
  cancelled: { key: "fanOuts.status.cancelled", tone: "neutral" },
  disabled: { key: "fanOuts.status.disabled", tone: "neutral" },
  failed: { key: "fanOuts.status.failed", tone: "danger" },
};

/** What each status means for the people who read the run, in one sentence. */
const STATUS_MEANING: Readonly<Record<FanOutStatus, MessageKey>> = {
  running: "fanOuts.meaning.running",
  held: "fanOuts.meaning.held",
  paused: "fanOuts.meaning.paused",
  completed: "fanOuts.meaning.completed",
  cancelled: "fanOuts.meaning.cancelled",
  disabled: "fanOuts.meaning.disabled",
  failed: "fanOuts.meaning.failed",
};

/** The controls each status allows, as the engine's routes state them. */
const CONTROLS: Readonly<Record<FanOutStatus, readonly FanOutControl[]>> = {
  running: ["pause", "cancel"],
  held: ["pause", "cancel"],
  paused: ["resume", "cancel"],
  completed: [],
  cancelled: [],
  disabled: [],
  failed: [],
};

const COUNT = new Intl.NumberFormat(LOCALE);

export function fanOutStatusLabel(status: FanOutStatus): string {
  return t(STATUS[status].key);
}

export function fanOutStatusTone(status: FanOutStatus): Tone {
  return STATUS[status].tone;
}

export function fanOutStatusMeaning(status: FanOutStatus): string {
  return t(STATUS_MEANING[status]);
}

export function controlsFor(status: FanOutStatus): readonly FanOutControl[] {
  return CONTROLS[status];
}

/** Whether the run has ended for good: nothing pauses, resumes or cancels it any more. */
export function isFinished(status: FanOutStatus): boolean {
  return CONTROLS[status].length === 0;
}

export function formatCount(value: number): string {
  return COUNT.format(value);
}

/** "1,000 of 2,000 decided". */
export function progressText(run: Pick<FanOutRun, "evaluated" | "businessesTotal">): string {
  return t("fanOuts.progress", {
    evaluated: formatCount(run.evaluated),
    total: formatCount(run.businessesTotal),
  });
}

/** "6 of 200 flipped (3%)", or that no business was compared with a superseded version. */
export function flipsText(run: Pick<FanOutRun, "flips" | "flipsCompared" | "flipRate">): string {
  if (run.flipsCompared === 0 || run.flipRate === null) return t("fanOuts.flips.none");
  return t("fanOuts.flips.some", {
    flips: formatCount(run.flips),
    compared: formatCount(run.flipsCompared),
    rate: `${Math.round(run.flipRate * 1000) / 10}%`,
  });
}

/**
 * Who changed a run or the hold, in words: a user by the start of their id, the engine itself
 * (the flip check, a withdrawal, or a caller without a token), or a service client.
 */
export function actorText(by: string | null): string | null {
  if (by === null || by.trim() === "") return null;
  if (by.startsWith("system:")) return t("fanOuts.by.system", { name: by.slice("system:".length) });
  if (by.startsWith("service:")) {
    return t("fanOuts.by.service", { name: by.slice("service:".length) });
  }
  return isUuid(by) ? t("fanOuts.by.user", { id: by.slice(0, 8) }) : by;
}

/** "example_rule v2", or the rule key alone when the version could not be read. */
export function versionName(
  run: Pick<FanOutRun, "ruleKey">,
  version: Pick<RuleVersion, "ruleKey" | "version"> | null,
): string {
  return version === null
    ? run.ruleKey
    : t("fanOuts.versionName", { rule: version.ruleKey, version: version.version });
}

/** The status's last change: "Paused by user 1a2b3c4d: Example reason", or null. */
export function lastChangeText(run: Pick<FanOutRun, "statusReason" | "statusBy">): string | null {
  const by = actorText(run.statusBy);
  const reason = run.statusReason.trim();
  if (by === null && reason === "") return null;
  if (by === null) return reason;
  return reason === ""
    ? t("fanOuts.lastChange.by", { by })
    : t("fanOuts.lastChange.byWithReason", { by, reason });
}

export interface FanOutRow {
  ruleVersionId: string;
  href: string;
  name: string;
  /** The version's title, when the rulebook answered. */
  title: string | null;
  status: FanOutStatus;
  statusLabel: string;
  statusTone: Tone;
  level: string;
  progress: string;
  applies: string;
  flips: string;
  started: string;
  startedIso: string;
  /** When it finished, or when it last moved while it runs. */
  lastMoved: string;
  lastChange: string | null;
}

export function fanOutRow(run: FanOutRun, version: RuleVersion | null, href: string): FanOutRow {
  return {
    ruleVersionId: run.ruleVersionId,
    href,
    name: versionName(run, version),
    title: version?.title ?? null,
    status: run.status,
    statusLabel: fanOutStatusLabel(run.status),
    statusTone: fanOutStatusTone(run.status),
    level: levelLabel(run.level),
    progress: progressText(run),
    applies: formatCount(run.applies),
    flips: flipsText(run),
    started: formatDateTime(run.startedAt),
    startedIso: run.startedAt,
    lastMoved:
      run.finishedAt === null
        ? t("fanOuts.updatedAt", { when: formatDateTime(run.updatedAt) })
        : t("fanOuts.finishedAt", { when: formatDateTime(run.finishedAt) }),
    lastChange: lastChangeText(run),
  };
}

export function holdView(hold: FanOutHold): HoldView {
  return {
    held: hold.held,
    reason: hold.reason === null || hold.reason.trim() === "" ? null : hold.reason,
    by: actorText(hold.setBy),
    since: hold.setAt === null ? null : formatDateTime(hold.setAt),
  };
}

/** The list's next page by the engine's cursor, and back to the newest from a later one. */
export function listHrefs(
  pathname: string,
  cursor: string | null,
  nextCursor: string | null,
): { nextHref: string | null; firstHref: string | null } {
  return {
    nextHref: nextCursor === null ? null : withQuery(pathname, { cursor: nextCursor }),
    firstHref: cursor === null ? null : pathname,
  };
}

/** The `cursor` of the address, when it is one the engine could have written. */
export function readCursor(value: string | string[] | undefined): string | null {
  const text = Array.isArray(value) ? value[0] : value;
  if (text === undefined || text === "" || text.length > 512) return null;
  return /^[A-Za-z0-9_-]+$/.test(text) ? text : null;
}
