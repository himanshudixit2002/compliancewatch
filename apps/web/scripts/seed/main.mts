import { randomUUID } from "node:crypto";
import { SeedError, seedClients } from "./http.mts";
import {
  DEFAULT_STATE_PATH,
  USAGE,
  UsageError,
  parseArgs,
  serviceUrls,
  writeToken,
} from "./lib.mts";
import { seedState, summary, writeSeedState, type SeedReport } from "./report.mts";
import { seedConsents } from "./steps/consents.mts";
import { seedNotificationPreference } from "./steps/notification.mts";
import { seedProfile } from "./steps/profile.mts";
import { seedRulebook } from "./steps/rulebook.mts";

/**
 * Fills the running services with the demo tenant over their HTTP APIs, in the order the
 * onboarding walks them, and records the tenant for the development sign-in:
 *
 *   1. identity      the owner's four consents
 *   2. profile       the registration and its entity, the GSTIN pre-fill, the answers
 *   3. notification  the owner's WhatsApp preference
 *   4. rulebook      one recorded CBIC notification with its clauses, mentions and relation
 *                    candidate (--skip-rulebook leaves it out; needs the write token)
 *
 *   pnpm --filter web seed [-- --tenant <uuid> --owner <uuid> --json --skip-rulebook]
 *   make web-seed [ARGS="..."]
 *
 * The service URLs come from CW_WEB_<SERVICE>_URL (apps/web/.env.local), else from
 * SERVICE_PORT_BASE (the root .env, which make web-seed sources), else the canonical 8001-8010.
 * A failed step stops the run (later steps need its ids) and the exit code is 1; the one
 * failure the run goes past, the mention alignment answering 422, still makes the exit code 1.
 * Nothing here is a mock: every call reaches a service.
 */
async function main(argv: readonly string[]): Promise<number> {
  let options;
  try {
    options = parseArgs(argv, {
      tenantId: randomUUID(),
      ownerId: randomUUID(),
      statePath: process.env.CW_WEB_SEED_STATE_PATH?.trim() || DEFAULT_STATE_PATH,
    });
  } catch (error) {
    if (!(error instanceof UsageError)) throw error;
    console.error(`${error.message}\n${USAGE}`);
    return 2;
  }
  if (options.help) {
    console.log(USAGE);
    return 0;
  }
  const services = serviceUrls(process.env);
  const clients = seedClients(services, options.tenantId, writeToken(process.env));
  const log = (line: string): void => {
    if (!options.json) console.log(line);
  };
  const report: SeedReport = {
    tenantId: options.tenantId,
    ownerId: options.ownerId,
    seededAt: new Date().toISOString(),
    services,
    consents: null,
    profile: null,
    notification: null,
    rulebook: null,
    rulebookSkipped: options.skipRulebook,
    failures: [],
  };
  log(`seeding tenant ${options.tenantId} (owner ${options.ownerId})`);
  try {
    report.consents = await seedConsents(clients, options.ownerId, log);
    report.profile = await seedProfile(clients, options.ownerId, log);
    report.notification = await seedNotificationPreference(clients, log);
    if (!options.skipRulebook) {
      report.rulebook = await seedRulebook(clients, log);
      if (report.rulebook.optionalFailure !== null) {
        report.failures.push(report.rulebook.optionalFailure);
      }
    }
  } catch (error) {
    if (!(error instanceof SeedError)) throw error;
    report.failures.push(error.failure);
  }
  const state = seedState(report);
  const statePath = state === null ? null : await writeSeedState(options.statePath, state);
  if (options.json) {
    console.log(JSON.stringify({ ...report, statePath }, null, 2));
  } else {
    console.log(summary(report, statePath));
  }
  return report.failures.length === 0 ? 0 : 1;
}

main(process.argv.slice(2)).then(
  (status) => {
    process.exitCode = status;
  },
  (error: unknown) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  },
);
