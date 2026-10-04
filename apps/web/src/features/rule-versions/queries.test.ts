// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { clauseDetailFromDto, relationFromDto } from "@/entities/rulebook/mappers";
import type { ClauseDetail, RuleRelation } from "@/entities/rulebook/types";
import { citationFromDto, ruleFromDto, ruleVersionFromDto } from "@/entities/rule-version/mappers";
import type { Citation, RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { err, ok, webError, type Result } from "@/server/result";
import { ontologyFixture } from "@/test/ontology-fixture";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import {
  EXAMPLE_OTHER_VERSION_ID,
  EXAMPLE_VERSION_ID,
  citationDto,
  ruleDto,
  ruleVersionDto,
} from "@/test/rule-version-fixture";
import type { VersionListFilter } from "./model/list-filter";
import { PAGE_SIZE } from "./model/version-list";
import type { RuleVersionsPort } from "./ports";
import { getVersionList, getVersionPage } from "./queries";

const analyst: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b1",
  tenantId: "00000000-0000-4000-8000-000000000001",
  tenantKind: "internal",
  roles: ["analyst"],
};

const FILTER: VersionListFilter = {
  status: "in_force",
  asOf: "2000-06-30",
  asOfGiven: false,
  ruleKey: null,
  after: null,
};

const failure = webError("server", "web-example", "Example failure");

function key(index: number): string {
  return `example_${String(index).padStart(2, "0")}`;
}

function version(index: number, status: RuleVersion["status"] = "draft"): RuleVersion {
  return ruleVersionFromDto(
    ruleVersionDto({
      rule_key: key(index),
      rule_version_id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      status,
    }),
  );
}

/** An in-memory port: rules by index, each with one version, the statuses alternating. */
class FakePort implements RuleVersionsPort {
  readonly calls: string[] = [];
  constructor(
    readonly count: number,
    readonly overrides: Partial<{
      rules: Result<readonly RuleSummary[]>;
      versionsOf: (ruleKey: string) => Result<readonly RuleVersion[]>;
      inForce: Result<readonly RuleVersion[]>;
      version: (id: string) => Result<RuleVersion>;
      citations: Result<readonly Citation[]>;
      clause: Result<ClauseDetail>;
      relations: (query: { from?: string; to?: string }) => Result<readonly RuleRelation[]>;
    }> = {},
  ) {}

  async rules() {
    this.calls.push("rules");
    return (
      this.overrides.rules ??
      ok(
        Array.from({ length: this.count }, (_, index) =>
          ruleFromDto(ruleDto({ rule_key: key(this.count - index - 1) })),
        ),
      )
    );
  }

  async versionsOf(ruleKey: string) {
    this.calls.push(`versions:${ruleKey}`);
    if (this.overrides.versionsOf !== undefined) return this.overrides.versionsOf(ruleKey);
    const index = Number(ruleKey.slice("example_".length));
    return ok([version(index, index % 2 === 0 ? "draft" : "in_review")]);
  }

  async inForce(query: { asOf: string; ruleKey?: string; limit: number; after?: string }) {
    this.calls.push(`in-force:${JSON.stringify(query)}`);
    return (
      this.overrides.inForce ??
      ok(Array.from({ length: query.limit }, (_, index) => version(index, "published")))
    );
  }

  async version(id: string) {
    this.calls.push(`version:${id}`);
    if (this.overrides.version !== undefined) return this.overrides.version(id);
    return ok(ruleVersionFromDto(ruleVersionDto({ rule_version_id: id })));
  }

  async citations() {
    return this.overrides.citations ?? ok([citationFromDto(citationDto())]);
  }

  async clause() {
    return (
      this.overrides.clause ??
      ok(
        clauseDetailFromDto({
          clause_id: EXAMPLE_CLAUSE_IDS.first,
          document_id: EXAMPLE_DOCUMENT_ID,
          clause_ref: "en.p1",
          ordinal: 1,
          page: 1,
          text: "Example clause text that opens the document.",
          regulator: "Example regulator",
          doc_type: "circular",
          external_ref: "Example 1/2000",
          title: "Example document title",
          url: "https://example.com/example.pdf",
          language: "en",
          published_at: null,
        }),
      )
    );
  }

  async relations(query: { from?: string; to?: string }) {
    if (this.overrides.relations !== undefined) return this.overrides.relations(query);
    return ok([]);
  }
}

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getVersionList", () => {
  it("pages the in-force list by rule key, asking one row more than a page", async () => {
    const port = new FakePort(3);
    const list = await getVersionList(FILTER, { port });
    if (!list.ok) throw new Error("expected the list");
    expect(list.value.rows).toHaveLength(PAGE_SIZE);
    expect(list.value.nextHref).toBe(`/admin/rulebook/versions?after=${key(PAGE_SIZE - 1)}`);
    expect(list.value.firstHref).toBeNull();
    expect(list.value.rules.map((rule) => rule.value)).toEqual([key(0), key(1), key(2)]);
    expect(port.calls).toContain(
      `in-force:${JSON.stringify({ asOf: "2000-06-30", limit: PAGE_SIZE + 1 })}`,
    );
  });

  it("has no next page when the rulebook returns a page or less", async () => {
    const port = new FakePort(1, { inForce: ok([version(0, "published")]) });
    const list = await getVersionList(
      { ...FILTER, ruleKey: "example_00", after: "example" },
      { port },
    );
    expect(list).toMatchObject({ ok: true, value: { nextHref: null } });
    if (!list.ok) return;
    expect(list.value.firstHref).toBe("/admin/rulebook/versions?rule=example_00");
    expect(port.calls).toContain(
      `in-force:${JSON.stringify({ asOf: "2000-06-30", limit: PAGE_SIZE + 1, ruleKey: "example_00", after: "example" })}`,
    );
  });

  it("fills a status page rule by rule from the cursor, and continues after the last rule read", async () => {
    const port = new FakePort(60);
    const list = await getVersionList({ ...FILTER, status: "draft" }, { port });
    if (!list.ok) throw new Error("expected the list");
    // Every other rule has a draft: 56 rules (seven batches of eight) hold 28 drafts.
    expect(list.value.rows).toHaveLength(28);
    expect(list.value.rows.every((row) => row.status === "draft")).toBe(true);
    expect(list.value.nextHref).toBe(`/admin/rulebook/versions?status=draft&after=${key(55)}`);
    const next = await getVersionList(
      { ...FILTER, status: "draft", after: key(55) },
      { port: new FakePort(60) },
    );
    expect(next.ok && next.value.rows.map((row) => row.ruleKey)).toEqual([key(56), key(58)]);
    expect(next.ok && next.value.nextHref).toBeNull();
  });

  it("reads one rule's versions only when a rule is chosen, every status for all", async () => {
    const port = new FakePort(5);
    const list = await getVersionList({ ...FILTER, status: "all", ruleKey: key(3) }, { port });
    expect(list.ok && list.value.rows.map((row) => row.ruleKey)).toEqual([key(3)]);
    expect(port.calls.filter((call) => call.startsWith("versions:"))).toEqual([
      `versions:${key(3)}`,
    ]);
  });

  it("skips a rule that went away and passes any other failure on", async () => {
    const gone = new FakePort(2, {
      versionsOf: (ruleKey) =>
        ruleKey === key(0) ? err(webError("not_found", "web-example", "Gone")) : ok([version(1)]),
    });
    expect(await getVersionList({ ...FILTER, status: "draft" }, { port: gone })).toMatchObject({
      ok: true,
      value: { rows: [{ ruleKey: key(1) }] },
    });
    const broken = new FakePort(2, { versionsOf: () => err(failure) });
    expect(await getVersionList({ ...FILTER, status: "draft" }, { port: broken })).toEqual(
      err(failure),
    );
    expect(
      await getVersionList(FILTER, { port: new FakePort(1, { rules: err(failure) }) }),
    ).toEqual(err(failure));
    expect(
      await getVersionList(FILTER, { port: new FakePort(1, { inForce: err(failure) }) }),
    ).toEqual(err(failure));
  });
});

describe("getVersionPage", () => {
  const relation = relationFromDto({
    relation_id: "00000000-0000-4000-8000-0000000000b1",
    from_rule_version_id: EXAMPLE_VERSION_ID,
    relation: "supersedes",
    to_kind: "rule_version",
    to_ref: EXAMPLE_OTHER_VERSION_ID,
    to_rule_version_id: EXAMPLE_OTHER_VERSION_ID,
    to_entity_id: null,
    evidence_clause_id: EXAMPLE_CLAUSE_IDS.first,
    evidence_clause_ref: "en.p1",
    evidence_document_id: EXAMPLE_DOCUMENT_ID,
    candidate_id: null,
    period_label: null,
    new_due_on: null,
  });

  it("puts the version, its condition in words, its citations, relations and steps together", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_PUBLISH_ACTIONS", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const port = new FakePort(1, {
      relations: (query) => ok(query.from === undefined ? [] : [relation]),
    });
    const page = await getVersionPage(
      EXAMPLE_VERSION_ID,
      { session: analyst },
      {
        port,
        ontology: async () => ok(ontologyFixture()),
      },
    );
    if (!page.ok) throw new Error("expected the page");
    expect(page.value.version.ruleVersionId).toBe(EXAMPLE_VERSION_ID);
    expect(page.value.specification).toMatchObject({ kind: "group", mode: "all_of" });
    expect(page.value.ontologyError).toBeNull();
    expect(page.value.citations).toMatchObject({
      ok: true,
      value: [
        {
          clause: { externalRef: "Example 1/2000" },
          quoteMark: { mark: "Example clause text that opens" },
        },
      ],
    });
    expect(page.value.relations).toMatchObject({
      ok: true,
      value: { from: [{ version: { label: "example_rule v1" } }], to: [] },
    });
    expect(port.calls).toContain(`version:${EXAMPLE_OTHER_VERSION_ID}`);
    expect(page.value.steps).toEqual(["submit"]);
    expect(page.value.access).toEqual({ allowed: true });
    expect(page.value.canCite).toBe(true);
    expect(page.value.graphHref).toContain(EXAMPLE_VERSION_ID);
  });

  it("keeps each failed part on its own and names the flag that holds the workflow back", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    const page = await getVersionPage(
      EXAMPLE_VERSION_ID,
      { session: analyst },
      {
        port: new FakePort(1, {
          version: (id) =>
            ok(
              ruleVersionFromDto(
                ruleVersionDto({ rule_version_id: id, status: "published", specification: {} }),
              ),
            ),
          citations: ok([citationFromDto(citationDto())]),
          clause: err(failure),
          relations: (query) => (query.to === undefined ? ok([]) : err(failure)),
        }),
        ontology: async () => err(failure),
      },
    );
    if (!page.ok) throw new Error("expected the page");
    expect(page.value.specification).toBeNull();
    expect(page.value.ontologyError).toBe(failure);
    expect(page.value.citations).toMatchObject({
      ok: true,
      value: [{ clause: null, quoteMark: null }],
    });
    expect(page.value.relations).toEqual({ ok: false, error: failure });
    expect(page.value.steps).toEqual(["withdraw"]);
    expect(page.value.canCite).toBe(false);
    expect(page.value.access).toMatchObject({
      allowed: false,
      title: "The web.publish_actions flag is off",
      flag: "web.publish_actions",
    });
  });

  it("answers the version's own failure, and keeps a failed citation read on its part", async () => {
    const missing = webError("not_found", "web-example", "Gone");
    expect(
      await getVersionPage(
        EXAMPLE_VERSION_ID,
        { session: analyst },
        {
          port: new FakePort(1, { version: () => err(missing) }),
        },
      ),
    ).toEqual(err(missing));
    const page = await getVersionPage(
      EXAMPLE_VERSION_ID,
      { session: analyst },
      {
        port: new FakePort(1, {
          citations: err(failure),
          relations: (query) => (query.from === undefined ? ok([]) : err(failure)),
        }),
        ontology: async () => ok(ontologyFixture()),
      },
    );
    expect(page).toMatchObject({
      ok: true,
      value: { citations: { ok: false, error: failure }, relations: { ok: false, error: failure } },
    });
  });
});
