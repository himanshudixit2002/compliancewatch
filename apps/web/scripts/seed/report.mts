import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { describeFailure, type SeedFailure } from "./http.mts";
import { seedStateJson, type SeedService, type SeedState } from "./lib.mts";
import type { ConsentsResult } from "./steps/consents.mts";
import type { NotificationResult } from "./steps/notification.mts";
import type { ProfileResult } from "./steps/profile.mts";
import type { RulebookResult } from "./steps/rulebook.mts";

/**
 * What one seed run produced: the ids the sign-in and the screens need, each step's counts,
 * and the failures. `writeSeedState` records the tenant for the development sign-in's "use the
 * last seeded tenant" option (CW_WEB_SEED_STATE_PATH, var/seed/last.json by default);
 * `summary` is the human report, `--json` prints the whole object.
 */
export interface SeedReport {
  tenantId: string;
  ownerId: string;
  seededAt: string;
  services: Record<SeedService, string>;
  consents: ConsentsResult | null;
  profile: ProfileResult | null;
  notification: NotificationResult | null;
  rulebook: RulebookResult | null;
  rulebookSkipped: boolean;
  failures: SeedFailure[];
}

export function seedState(report: SeedReport): SeedState | null {
  if (report.profile === null) return null;
  return {
    tenant_id: report.tenantId,
    owner_id: report.ownerId,
    entity_node_id: report.profile.entityNodeId,
    registration_node_id: report.profile.registrationNodeId,
    document_id: report.rulebook?.documentId ?? null,
    seeded_at: report.seededAt,
    services: report.services,
  };
}

/** Writes the state file (creating its directory) and returns the absolute path. */
export async function writeSeedState(statePath: string, state: SeedState): Promise<string> {
  const target = resolve(process.cwd(), statePath);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, seedStateJson(state), "utf8");
  return target;
}

export function summary(report: SeedReport, statePath: string | null): string {
  const lines: string[] = [];
  const outcome = report.failures.length === 0 ? "Seeded" : "Seeding failed for";
  lines.push(
    `${outcome} tenant ${report.tenantId} (owner ${report.ownerId}) at ${report.seededAt}`,
  );
  if (report.consents !== null) {
    lines.push(
      `  consents      ${report.consents.granted.length} granted: ${report.consents.granted.join(", ")}`,
    );
  }
  if (report.profile !== null) {
    const p = report.profile;
    lines.push(
      `  profile       entity ${p.entityNodeId}, registration ${p.registrationNodeId};` +
        ` ${p.prefilled.length} pre-filled, ${p.answered} answered, ${p.openReviewTasks} open review task(s)`,
    );
  }
  if (report.notification !== null) {
    const n = report.notification;
    lines.push(
      `  notification  ${n.channel} ${n.recipient} ${n.optedIn ? "opted in" : "not opted in"}, ${n.language}, quiet ${n.quietHours}`,
    );
  }
  if (report.rulebook !== null) {
    const r = report.rulebook;
    const mentions =
      r.mentions === null ? "mentions refused" : `${r.mentions.queued} mention(s) queued`;
    lines.push(
      `  rulebook      document ${r.documentId} (${r.clauses} clauses); ${mentions};` +
        ` ${r.reviewGroups} review group(s), ${r.reviewCandidates} relation candidate(s)`,
    );
  } else if (report.rulebookSkipped) {
    lines.push("  rulebook      skipped (--skip-rulebook)");
  }
  if (statePath !== null) lines.push(`  state         ${statePath}`);
  for (const failure of report.failures) lines.push(`  FAILED        ${describeFailure(failure)}`);
  return lines.join("\n");
}
