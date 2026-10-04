// @vitest-environment node
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { serviceUrls } from "./lib.mts";
import { seedState, summary, writeSeedState, type SeedReport } from "./report.mts";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const OWNER = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const ENTITY = "11111111-1111-4111-8111-111111111111";
const REGISTRATION = "22222222-2222-4222-8222-222222222222";
const DOCUMENT = "33333333-3333-4333-8333-333333333333";

function emptyReport(): SeedReport {
  return {
    tenantId: TENANT,
    ownerId: OWNER,
    seededAt: "2000-01-01T00:00:00.000Z",
    services: serviceUrls({}),
    consents: null,
    profile: null,
    notification: null,
    rulebook: null,
    rulebookSkipped: false,
    failures: [],
  };
}

function fullReport(): SeedReport {
  return {
    ...emptyReport(),
    consents: { recorded: ["terms", "privacy_notice"], granted: ["terms", "privacy_notice"] },
    profile: {
      entityNodeId: ENTITY,
      registrationNodeId: REGISTRATION,
      created: true,
      prefilled: ["state_codes"],
      answered: 13,
      nextQuestion: null,
      snapshotAttributes: 17,
      openReviewTasks: 0,
    },
    notification: {
      channel: "whatsapp",
      recipient: "910000000000",
      optedIn: true,
      language: "hi",
      quietHours: "21:00-08:00",
      confirmation: { outcome: "failed", error: "example channel not wired" },
      history: { total: 1, states: ["queued"] },
    },
    rulebook: {
      documentId: DOCUMENT,
      created: true,
      metadataDiffers: [],
      clauses: 6,
      mentions: { sent: 5, aligned: 0, queued: 5, unchanged: 0 },
      candidates: { sent: 1, created: 1, unchanged: 0 },
      knownRules: 0,
      reviewGroups: 5,
      reviewCandidates: 1,
      optionalFailure: null,
    },
  };
}

describe("seedState", () => {
  it("records nothing until the profile step has produced the business", () => {
    expect(seedState(emptyReport())).toBeNull();
  });

  it("carries the ids the sign-in and the screens need", () => {
    expect(seedState(fullReport())).toEqual({
      tenant_id: TENANT,
      owner_id: OWNER,
      entity_node_id: ENTITY,
      registration_node_id: REGISTRATION,
      document_id: DOCUMENT,
      seeded_at: "2000-01-01T00:00:00.000Z",
      services: serviceUrls({}),
    });
    expect(seedState({ ...fullReport(), rulebook: null })?.document_id).toBeNull();
  });
});

describe("summary", () => {
  it("prints one line per step, the state file and every failure", () => {
    const report = fullReport();
    report.failures.push({ step: "rulebook", request: "PUT /m", status: 422, title: "Refused" });
    const text = summary(report, "/tmp/example/last.json");
    expect(text).toContain(`Seeding failed for tenant ${TENANT} (owner ${OWNER})`);
    expect(text).toContain("consents      2 granted: terms, privacy_notice");
    expect(text).toContain(`profile       entity ${ENTITY}, registration ${REGISTRATION}`);
    expect(text).toContain("notification  whatsapp 910000000000 opted in, hi, quiet 21:00-08:00");
    expect(text).toContain(
      "opt-in confirmation failed (example channel not wired); 1 notification(s) for the business: queued",
    );
    expect(text).toContain(`rulebook      document ${DOCUMENT} (6 clauses); 5 mention(s) queued`);
    expect(text).toContain("state         /tmp/example/last.json");
    expect(text).toContain('FAILED        rulebook: PUT /m -> 422 "Refused"');
  });

  it("says when the mentions were refused, the rulebook was skipped or nothing was recorded", () => {
    const deferred = fullReport();
    if (deferred.notification !== null) {
      deferred.notification.confirmation = { outcome: "deferred", error: "" };
    }
    expect(summary(deferred, null)).toContain(
      "opt-in confirmation deferred; 1 notification(s) for the business: queued",
    );
    const refused = fullReport();
    if (refused.rulebook !== null) refused.rulebook.mentions = null;
    expect(summary(refused, null)).toContain("mentions refused");
    expect(summary({ ...emptyReport(), rulebookSkipped: true }, null)).toContain(
      "rulebook      skipped (--skip-rulebook)",
    );
    expect(summary(emptyReport(), null).split("\n")).toEqual([
      `Seeded tenant ${TENANT} (owner ${OWNER}) at 2000-01-01T00:00:00.000Z`,
    ]);
  });
});

describe("writeSeedState", () => {
  let dir: string | null = null;

  afterEach(async () => {
    if (dir !== null) await rm(dir, { recursive: true, force: true });
    dir = null;
  });

  it("creates the directory and writes the state as JSON", async () => {
    dir = await mkdtemp(join(tmpdir(), "seed-state-"));
    const state = seedState(fullReport());
    if (state === null) throw new Error("expected a state");
    const target = await writeSeedState(join(dir, "nested", "last.json"), state);
    expect(target).toBe(join(dir, "nested", "last.json"));
    expect(JSON.parse(await readFile(target, "utf8"))).toEqual(state);
  });
});
