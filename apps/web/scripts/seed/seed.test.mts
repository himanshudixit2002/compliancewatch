// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  DEFAULT_PORT_BASE,
  DEFAULT_STATE_PATH,
  DEMO,
  PLACEHOLDER_WRITE_TOKEN,
  SEED_SERVICES,
  UsageError,
  VERSION_PATTERN,
  attributeChanges,
  documentIdFor,
  fixtureProblems,
  parseArgs,
  portBase,
  seedFinancialYear,
  seedStateJson,
  serviceUrl,
  serviceUrls,
  sha256Hex,
  withKnownRules,
  writeToken,
  type RulebookFixtures,
} from "./lib.mts";
import { FIXTURE_NAME, loadFixtures, recordedPdfBytes } from "./steps/rulebook.mts";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const OWNER = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const DEFAULTS = { tenantId: TENANT, ownerId: OWNER, statePath: DEFAULT_STATE_PATH };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

describe("the demo facts", () => {
  it("answers for the financial year of the as-of date", () => {
    expect(seedFinancialYear()).toBe("2026-27");
    expect(seedFinancialYear("2026-03-31")).toBe("2025-26");
  });

  it("puts turnover on the entity with its financial year and the filing facts on the registration", () => {
    const changes = attributeChanges("2026-27");
    expect(changes.entity.map((change) => change.key)).toEqual([
      "state_codes",
      "business_category",
      "turnover_band",
      "peak_turnover_band",
      "employee_count",
    ]);
    expect(changes.entity.find((change) => change.key === "turnover_band")).toEqual({
      key: "turnover_band",
      value: "2_crore_to_5_crore",
      as_of_fy: "2026-27",
    });
    expect(changes.entity.filter((change) => "as_of_fy" in change)).toHaveLength(1);
    expect(changes.registration).toHaveLength(8);
    expect(changes.registration.every((change) => !("as_of_fy" in change))).toBe(true);
    expect(changes.registration.map((change) => change.key)).toContain("filing_scheme");
  });

  it("uses the demo tenant's values", () => {
    expect(DEMO.gstin).toBe("29ABCDE1234F1Z5");
    expect(DEMO.ownerPhone).toBe("919876543210");
    expect(DEMO.noticeVersion).toBe("0.1-draft");
    expect(DEMO.consentPurposes).toEqual([
      "terms",
      "privacy_notice",
      "profile_processing",
      "whatsapp_reminders",
    ]);
  });
});

describe("service URLs and the write token", () => {
  it("lists the services in the Makefile's order", () => {
    expect(SEED_SERVICES).toEqual([
      "identity",
      "profile",
      "rulebook",
      "applicability-engine",
      "obligation",
      "notification",
      "qa",
      "llm-gateway",
      "eval",
      "pipeline",
    ]);
  });

  it("defaults to the canonical ports, moves with SERVICE_PORT_BASE, and lets the app's variable win", () => {
    expect(portBase({})).toBe(DEFAULT_PORT_BASE);
    expect(serviceUrl("identity", {})).toBe("http://localhost:8001");
    expect(serviceUrl("pipeline", {})).toBe("http://localhost:8010");
    expect(serviceUrl("rulebook", { SERVICE_PORT_BASE: "9200" })).toBe("http://localhost:9203");
    expect(
      serviceUrl("rulebook", { SERVICE_PORT_BASE: "9200", CW_WEB_RULEBOOK_URL: "http://rb:1/" }),
    ).toBe("http://rb:1");
    expect(serviceUrl("rulebook", { CW_WEB_RULEBOOK_URL: "  " })).toBe("http://localhost:8003");
    expect(Object.keys(serviceUrls({ SERVICE_PORT_BASE: "9200" }))).toEqual([...SEED_SERVICES]);
    expect(serviceUrls({ SERVICE_PORT_BASE: "9200" }).qa).toBe("http://localhost:9207");
  });

  it("refuses a port base that is not a port", () => {
    expect(() => portBase({ SERVICE_PORT_BASE: "nine" })).toThrow(/SERVICE_PORT_BASE/);
    expect(() => portBase({ SERVICE_PORT_BASE: "70000" })).toThrow(/SERVICE_PORT_BASE/);
  });

  it("takes the web variable, then the services' variable, then the stack's placeholder", () => {
    expect(writeToken({ CW_WEB_RULEBOOK_WRITE_TOKEN: "a", CW_RULEBOOK_WRITE_TOKEN: "b" })).toBe(
      "a",
    );
    expect(writeToken({ CW_RULEBOOK_WRITE_TOKEN: "b" })).toBe("b");
    expect(writeToken({ CW_RULEBOOK_WRITE_TOKEN: "" })).toBe(PLACEHOLDER_WRITE_TOKEN);
    expect(writeToken({})).toBe("local-write-token");
  });
});

describe("parseArgs", () => {
  it("keeps the defaults with no arguments", () => {
    expect(parseArgs([], DEFAULTS)).toEqual({
      ...DEFAULTS,
      json: false,
      skipRulebook: false,
      help: false,
    });
  });

  it("reads every option and lowercases the ids", () => {
    const options = parseArgs(
      [
        "--",
        "--tenant",
        TENANT.toUpperCase(),
        "--owner",
        OWNER,
        "--json",
        "--skip-rulebook",
        "--state",
        "x/y.json",
      ],
      DEFAULTS,
    );
    expect(options).toEqual({
      tenantId: TENANT,
      ownerId: OWNER,
      json: true,
      skipRulebook: true,
      statePath: "x/y.json",
      help: false,
    });
    expect(parseArgs(["--help"], DEFAULTS).help).toBe(true);
    expect(parseArgs(["-h"], DEFAULTS).help).toBe(true);
  });

  it("refuses an unknown option, a missing value and an id that is not a UUID", () => {
    expect(() => parseArgs(["--tenants"], DEFAULTS)).toThrow(UsageError);
    expect(() => parseArgs(["--tenant"], DEFAULTS)).toThrow(/needs a value/);
    expect(() => parseArgs(["--tenant", "--json"], DEFAULTS)).toThrow(/needs a value/);
    expect(() => parseArgs(["--owner", "owner-1"], DEFAULTS)).toThrow(/must be a UUID/);
  });
});

describe("document ids and digests", () => {
  it("reads the first half of the digest as a UUID, as the kernel does", () => {
    const sha = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed";
    expect(documentIdFor(sha)).toBe("51f5dbee-1615-f0ec-4725-6abddb11061a");
    expect(() => documentIdFor("abc")).toThrow(/64 lowercase hex/);
    expect(() => documentIdFor(sha.toUpperCase())).toThrow(/64 lowercase hex/);
  });

  it("hashes bytes to lowercase hex", () => {
    expect(sha256Hex(new Uint8Array())).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });
});

describe("the recorded rulebook fixtures", () => {
  it("parse, hash to the recorded PDF and slice their clauses exactly", async () => {
    const fixtures = await loadFixtures();
    const pdf = await recordedPdfBytes();
    expect(fixtureProblems(fixtures, pdf)).toEqual([]);
    expect(FIXTURE_NAME).toBe("gst-ct-01-2026");
    expect(documentIdFor(fixtures.document.sha256)).toMatch(UUID);
    expect(fixtures.document.parser_version).toMatch(VERSION_PATTERN);
    expect(fixtures.mentions.extractor).toMatch(VERSION_PATTERN);
    expect(fixtures.document.clauses.length).toBeGreaterThan(0);
    expect(fixtures.mentions.mentions.length).toBeGreaterThan(0);
    expect(fixtures.relations.candidates.length).toBeGreaterThan(0);
    expect(fixtures.document.external_ref).toBe("01/2026-Central Tax");
  });

  it("report a digest mismatch, a mention off its span, a target that is no mention and a quote outside its clause", () => {
    const fixtures: RulebookFixtures = {
      document: {
        source_id: "00000000-0000-4000-8000-00000000000b",
        sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        regulator: "EXAMPLE",
        doc_type: "notification",
        external_ref: "example",
        url: "https://example.invalid/example.pdf",
        title: "Example title",
        language: "en",
        media_type: "application/pdf",
        parser_version: "pdf@1",
        published_at: null,
        fetched_at: "2000-01-01T00:00:00+00:00",
        raw_uri: null,
        clauses: [{ clause_ref: "en.p1", text: "Example clause text", page: 1 }],
      },
      mentions: {
        extractor: "grammar@1",
        mentions: [
          {
            clause_ref: "en.p1",
            entity_type: "form",
            text: "clause",
            span_start: 8,
            span_end: 14,
            proposed_name: "clause",
          },
          {
            clause_ref: "en.p1",
            entity_type: "form",
            text: "clause",
            span_start: 0,
            span_end: 6,
            proposed_name: "clause",
          },
          {
            clause_ref: "en.p9",
            entity_type: "form",
            text: "clause",
            span_start: 0,
            span_end: 6,
            proposed_name: "clause",
          },
        ],
      },
      relations: {
        extractor: "extraction.rule_relations@1",
        model: "scripted/golden",
        outcome: "ok",
        run_issues: [],
        candidates: [
          {
            relation: "extends_deadline",
            target_type: "form",
            target_name: "clause",
            target_clause_ref: "en.p1",
            target_span_start: 8,
            target_span_end: 14,
            rule_key: null,
            evidence_clause_ref: "en.p1",
            evidence_quote: "Example clause",
            quote_score: 1,
            period_label: null,
            new_due_on: null,
            confidence: 0.5,
            issues: [],
            needs_review: true,
          },
          {
            relation: "extends_deadline",
            target_type: "section",
            target_name: "clause",
            target_clause_ref: "en.p1",
            target_span_start: 8,
            target_span_end: 14,
            rule_key: null,
            evidence_clause_ref: "en.p1",
            evidence_quote: "not in the clause",
            quote_score: 1,
            period_label: null,
            new_due_on: null,
            confidence: 0.5,
            issues: [],
            needs_review: true,
          },
        ],
      },
    };
    const problems = fixtureProblems(fixtures, new TextEncoder().encode("other bytes"));
    expect(problems).toHaveLength(5);
    expect(problems[0]).toMatch(/hashes to/);
    expect(problems[1]).toMatch(/is not en\.p1\[0:6\]/);
    expect(problems[2]).toMatch(/unknown clause en\.p9/);
    expect(problems[3]).toMatch(
      /candidate target "clause" \(section\) is not a recorded mention at en\.p1\[8:14\]/,
    );
    expect(problems[4]).toMatch(/evidence quote is not in en\.p1/);
    const matchingDigest = fixtureProblems(fixtures, new Uint8Array());
    expect(matchingDigest).toHaveLength(4);
    expect(matchingDigest.some((problem) => problem.includes("hashes to"))).toBe(false);
  });

  it("keep a candidate's rule key only when the rulebook lists the rule", async () => {
    const { relations } = await loadFixtures();
    const keys = relations.candidates.map((candidate) => candidate.rule_key);
    expect(keys.some((key) => key !== null)).toBe(true);
    expect(withKnownRules(relations, []).candidates.map((c) => c.rule_key)).toEqual(
      keys.map(() => null),
    );
    const known = keys.filter((key): key is string => key !== null);
    expect(withKnownRules(relations, known).candidates.map((c) => c.rule_key)).toEqual(keys);
    expect(withKnownRules(relations, known)).not.toBe(relations);
  });
});

describe("seedStateJson", () => {
  it("writes the fields the sign-in reads back, with a trailing newline", () => {
    const json = seedStateJson({
      tenant_id: TENANT,
      owner_id: OWNER,
      entity_node_id: TENANT,
      registration_node_id: OWNER,
      document_id: null,
      seeded_at: "2000-01-01T00:00:00.000Z",
      services: serviceUrls({}),
    });
    expect(json.endsWith("\n")).toBe(true);
    const parsed = JSON.parse(json) as { tenant_id: string; seeded_at: string; document_id: null };
    expect(parsed.tenant_id).toBe(TENANT);
    expect(parsed.seeded_at).toBe("2000-01-01T00:00:00.000Z");
    expect(parsed.document_id).toBeNull();
  });
});
