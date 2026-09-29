import { readFile } from "node:fs/promises";
import { SeedError, expectOk, type SeedClients, type SeedFailure } from "../http.mts";
import {
  documentFixtureSchema,
  documentIdFor,
  fixtureProblems,
  mentionsFixtureSchema,
  relationsFixtureSchema,
  withKnownRules,
  type RulebookFixtures,
} from "../lib.mts";

/**
 * One recorded CBIC notification into the rulebook, replayed from the fixtures next to this
 * script (fixtures/rulebook/README.md says how they were recorded): the document with its
 * clauses, the mentions the grammar found, and the relation candidate the demo's scripted
 * answer stages. The recorded PDF is hashed first and must match the fixture, so a re-recorded
 * PDF or an edited fixture fails loudly instead of seeding something the pipeline never saw.
 * The mentions and the candidate go to the review queues, which is what the admin screens list.
 */
export const FIXTURE_NAME = "gst-ct-01-2026";
const FIXTURE_DIR = new URL("../fixtures/rulebook/", import.meta.url);
const PDF_WRAPPER = new URL(
  `../../../../../services/pipeline/tests/fixtures/cbic/${FIXTURE_NAME}.pdf.json`,
  import.meta.url,
);

export interface RulebookResult {
  documentId: string;
  created: boolean;
  metadataDiffers: string[];
  clauses: number;
  mentions: { sent: number; aligned: number; queued: number; unchanged: number } | null;
  candidates: { sent: number; created: number; unchanged: number };
  knownRules: number;
  reviewGroups: number;
  reviewCandidates: number;
  /** A failure the seed went past (the mention alignment); the exit code still reports it. */
  optionalFailure: SeedFailure | null;
}

async function readJson(url: URL): Promise<unknown> {
  return JSON.parse(await readFile(url, "utf8")) as unknown;
}

export async function loadFixtures(): Promise<RulebookFixtures> {
  const [document, mentions, relations] = await Promise.all([
    readJson(new URL(`${FIXTURE_NAME}.document.json`, FIXTURE_DIR)),
    readJson(new URL(`${FIXTURE_NAME}.mentions.json`, FIXTURE_DIR)),
    readJson(new URL(`${FIXTURE_NAME}.relations.json`, FIXTURE_DIR)),
  ]);
  return {
    document: documentFixtureSchema.parse(document),
    mentions: mentionsFixtureSchema.parse(mentions),
    relations: relationsFixtureSchema.parse(relations),
  };
}

export async function recordedPdfBytes(): Promise<Uint8Array> {
  const wrapper = (await readJson(PDF_WRAPPER)) as { data?: unknown };
  if (typeof wrapper.data !== "string") {
    throw new Error(`${PDF_WRAPPER.pathname} has no base64 "data" field`);
  }
  return new Uint8Array(Buffer.from(wrapper.data, "base64"));
}

export async function seedRulebook(
  clients: SeedClients,
  log: (line: string) => void,
): Promise<RulebookResult> {
  const step = "rulebook";
  const fixtures = await loadFixtures();
  const problems = fixtureProblems(fixtures, await recordedPdfBytes());
  if (problems.length > 0) {
    throw new Error(
      `rulebook: the fixtures under scripts/seed/fixtures/rulebook do not agree with the recorded PDF;` +
        ` re-record them (see the README there):\n  ${problems.join("\n  ")}`,
    );
  }
  const documentId = documentIdFor(fixtures.document.sha256);
  const path = { document_id: documentId };
  const registered = await expectOk(
    step,
    "PUT /v1/rulebook/documents/{document_id}",
    clients.rulebookAdmin.PUT("/v1/rulebook/documents/{document_id}", {
      params: { path },
      body: fixtures.document,
    }),
    {
      401: "the write token differs from the rulebook's CW_RULEBOOK_WRITE_TOKEN; set CW_WEB_RULEBOOK_WRITE_TOKEN to the same value",
      409: "the rulebook holds this document with other clauses; a memory store forgets it on restart (make web-stack-down, make web-stack)",
      503: "the rulebook refuses writes without a token: set CW_RULEBOOK_WRITE_TOKEN for the rulebook (make web-stack does) and CW_WEB_RULEBOOK_WRITE_TOKEN here",
    },
  );
  const result: RulebookResult = {
    documentId,
    created: registered.data.created,
    metadataDiffers: [...registered.data.metadata_differs],
    clauses: fixtures.document.clauses.length,
    mentions: null,
    candidates: { sent: fixtures.relations.candidates.length, created: 0, unchanged: 0 },
    knownRules: 0,
    reviewGroups: 0,
    reviewCandidates: 0,
    optionalFailure: null,
  };
  log(
    `rulebook: document ${documentId} ${result.created ? "created" : "already there"}` +
      ` (${result.clauses} clauses, ${fixtures.document.external_ref})` +
      (result.metadataDiffers.length === 0
        ? ""
        : `; stored metadata differs in ${result.metadataDiffers.join(", ")}`),
  );
  try {
    const aligned = await expectOk(
      step,
      "PUT /v1/rulebook/documents/{document_id}/mentions",
      clients.rulebookAdmin.PUT("/v1/rulebook/documents/{document_id}/mentions", {
        params: { path },
        body: fixtures.mentions,
      }),
    );
    result.mentions = {
      sent: fixtures.mentions.mentions.length,
      aligned: aligned.data.aligned,
      queued: aligned.data.queued,
      unchanged: aligned.data.unchanged,
    };
    log(
      `rulebook: ${result.mentions.sent} mentions sent, ${result.mentions.aligned} aligned,` +
        ` ${result.mentions.queued} queued for review, ${result.mentions.unchanged} unchanged`,
    );
  } catch (error) {
    if (!(error instanceof SeedError) || error.failure.status !== 422) throw error;
    result.optionalFailure = error.failure;
    log(`rulebook: the mentions were refused; continuing (${error.message})`);
  }
  const rules = await expectOk(
    step,
    "GET /v1/rulebook/rules",
    clients.rulebook.GET("/v1/rulebook/rules"),
  );
  const knownRuleKeys = rules.data.map((rule) => rule.rule_key);
  result.knownRules = knownRuleKeys.length;
  const relations = withKnownRules(fixtures.relations, knownRuleKeys);
  const staged = await expectOk(
    step,
    "PUT /v1/rulebook/documents/{document_id}/relation-candidates",
    clients.rulebookAdmin.PUT("/v1/rulebook/documents/{document_id}/relation-candidates", {
      params: { path },
      body: relations,
    }),
  );
  result.candidates.created = staged.data.created;
  result.candidates.unchanged = staged.data.unchanged;
  const dropped = fixtures.relations.candidates.filter(
    (candidate, index) =>
      candidate.rule_key !== null && relations.candidates[index]?.rule_key === null,
  ).length;
  log(
    `rulebook: ${result.candidates.sent} relation candidate(s) sent, ${staged.data.created} created,` +
      ` ${staged.data.unchanged} unchanged; ${knownRuleKeys.length} rule(s) known` +
      (dropped === 0 ? "" : ` (${dropped} rule key(s) blanked: not in this rulebook)`),
  );
  const groups = await expectOk(
    step,
    "GET /v1/rulebook/review/entities",
    clients.rulebook.GET("/v1/rulebook/review/entities"),
  );
  const candidates = await expectOk(
    step,
    "GET /v1/rulebook/review/relations?document_id=",
    clients.rulebook.GET("/v1/rulebook/review/relations", {
      params: { query: { document_id: documentId } },
    }),
  );
  result.reviewGroups = groups.data.length;
  result.reviewCandidates = candidates.data.length;
  log(
    `rulebook: review queues hold ${result.reviewGroups} entity group(s)` +
      ` and ${result.reviewCandidates} candidate(s) for this document`,
  );
  return result;
}
