import { randomBytes, randomInt, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, serviceUrl } from "./fixtures";

/**
 * Reads of the rulebook the rulebook specs compare the pages with, straight from the service the
 * stack runs (`make web-stack` starts it with the seed calendar's drafts; `make web-seed`
 * registers the recorded notification). Every decision a spec makes goes through the web app as a
 * signed-in analyst of the fake sign-in. The one write here is `stageReview`: a decision closes
 * what it decides, so the review specs stage a synthetic document of their own for each run
 * through the pipeline's routes (the write token, as the seed sends it), and decide that.
 */
export interface RuleRow {
  rule_key: string;
  title: string;
}

export interface VersionRow {
  rule_version_id: string;
  rule_key: string;
  version: number;
  status: string;
  title: string;
  seed_status: string;
  high_impact: boolean;
  effective_from: string;
  todo: string[];
  specification: Record<string, unknown>;
}

export async function rulebookGet<T>(path: string): Promise<T> {
  const response = await fetch(`${serviceUrl("rulebook")}${path}`);
  expect(response.status, `GET ${path} on the rulebook`).toBe(200);
  return (await response.json()) as T;
}

/** The rules by key, in the order the rulebook pages them. */
export async function ruleKeys(): Promise<string[]> {
  const rules = await rulebookGet<RuleRow[]>("/v1/rulebook/rules");
  expect(rules.length, "the rulebook starts with the seed calendar's drafts").toBeGreaterThan(4);
  return rules.map((rule) => rule.rule_key).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
}

export async function versionsOf(ruleKey: string): Promise<VersionRow[]> {
  return rulebookGet<VersionRow[]>(`/v1/rulebook/rules/${ruleKey}/versions`);
}

/** The latest version of the rule at a position in the key order. */
export async function latestVersion(position: number): Promise<VersionRow> {
  const key = (await ruleKeys())[position];
  if (key === undefined) throw new Error(`the rulebook holds no rule at position ${position}`);
  const versions = await versionsOf(key);
  const latest = versions.at(-1);
  if (latest === undefined) throw new Error(`rule at position ${position} has no version`);
  return latest;
}

export async function versionNow(ruleVersionId: string): Promise<VersionRow> {
  return rulebookGet<VersionRow>(`/v1/rulebook/rule-versions/${ruleVersionId}`);
}

/** The predicates' attributes in a stored condition, in order. */
export function conditionAttributes(node: unknown): string[] {
  if (typeof node !== "object" || node === null) return [];
  const record = node as Record<string, unknown>;
  if (Array.isArray(record.all_of)) return record.all_of.flatMap(conditionAttributes);
  if (Array.isArray(record.any_of)) return record.any_of.flatMap(conditionAttributes);
  if ("not" in record) return conditionAttributes(record.not);
  return typeof record.attribute === "string" ? [record.attribute] : [];
}

interface RecordedDocument {
  sha256: string;
  title: string;
  external_ref: string;
  clauses: { clause_ref: string; text: string }[];
}

const RECORDED = JSON.parse(
  readFileSync(
    resolve(__dirname, "../scripts/seed/fixtures/rulebook/gst-ct-01-2026.document.json"),
    "utf8",
  ),
) as RecordedDocument;

/** The recorded notification `make web-seed` registers, with its id and its clauses' text. */
export const RECORDED_DOCUMENT = {
  ...RECORDED,
  documentId: (() => {
    const hex = RECORDED.sha256.slice(0, 32);
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  })(),
  textOf(clauseRef: string): string {
    const clause = RECORDED.clauses.find((candidate) => candidate.clause_ref === clauseRef);
    if (clause === undefined) throw new Error(`the recorded document has no clause ${clauseRef}`);
    return clause.text;
  },
};

/** The ids the rulebook gave the recorded clauses. */
export async function recordedClauseIds(): Promise<Record<string, string>> {
  const body = await rulebookGet<{ clauses: { clause_id: string; clause_ref: string }[] }>(
    `/v1/rulebook/documents/${RECORDED_DOCUMENT.documentId}`,
  );
  return Object.fromEntries(body.clauses.map((clause) => [clause.clause_ref, clause.clause_id]));
}

/** The write token the stack gave the rulebook, as `make web-e2e` passes it to the run. */
function writeToken(): string {
  return process.env.CW_WEB_RULEBOOK_WRITE_TOKEN?.trim() || "local-write-token";
}

async function rulebookPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${serviceUrl("rulebook")}${path}`, {
    method: "PUT",
    headers: { "content-type": "application/json", "x-cw-write-token": writeToken() },
    body: JSON.stringify(body),
  });
  // 201 for a document registered now, 200 for the staging routes.
  expect([200, 201], `PUT ${path} on the rulebook: ${await response.clone().text()}`).toContain(
    response.status,
  );
  return (await response.json()) as T;
}

export interface StagedReview {
  documentId: string;
  /** One form name per review group, each unique to this run ("EX-123456789"). */
  names: string[];
  /** The relation candidates staged, in the order asked. */
  candidateIds: string[];
}

/**
 * A synthetic document of one clause naming `forms` forms, each an open review group of its own,
 * and, for each relation asked, a relation candidate targeting the form at that index with a quote
 * of the clause as its evidence. Every name is new, so a run decides groups and candidates no
 * other run or spec has touched.
 */
export async function stageReview(
  forms: number,
  relations: readonly { relation: string; target: number }[] = [],
): Promise<StagedReview> {
  const sha256 = randomBytes(32).toString("hex");
  const hex = sha256.slice(0, 32);
  const documentId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  const names = Array.from({ length: forms }, () => `EX-${randomInt(100_000_000, 999_999_999)}`);
  const text = `Example clause naming form ${names.join(" and form ")} for the review queue.`;
  const spans = names.map((name) => {
    const start = text.indexOf(name);
    return { start, end: start + name.length };
  });
  await rulebookPut(`/v1/rulebook/documents/${documentId}`, {
    source_id: randomUUID(),
    sha256,
    regulator: "EXAMPLE",
    doc_type: "circular",
    external_ref: `Example ${names[0] ?? "document"}`,
    url: "https://example.com/example-review-document.pdf",
    title: "Example document staged for the review queues",
    language: "en",
    media_type: "application/pdf",
    parser_version: "example@1",
    fetched_at: "2000-01-01T00:00:00Z",
    published_at: "2000-01-01",
    clauses: [{ clause_ref: "en.p1", page: 1, text }],
  });
  await rulebookPut(`/v1/rulebook/documents/${documentId}/mentions`, {
    extractor: "example@1",
    mentions: names.map((name, index) => ({
      clause_ref: "en.p1",
      entity_type: "form",
      text: name,
      span_start: spans[index]?.start,
      span_end: spans[index]?.end,
      proposed_name: name,
    })),
  });
  let candidateIds: string[] = [];
  if (relations.length > 0) {
    const staged = await rulebookPut<{ candidate_ids: string[] }>(
      `/v1/rulebook/documents/${documentId}/relation-candidates`,
      {
        extractor: "example.relations@1",
        model: "example/model",
        outcome: "ok",
        run_issues: [],
        candidates: relations.map(({ relation, target }) => ({
          relation,
          target_type: "form",
          target_name: names[target],
          target_clause_ref: "en.p1",
          target_span_start: spans[target]?.start,
          target_span_end: spans[target]?.end,
          rule_key: null,
          evidence_clause_ref: "en.p1",
          evidence_quote: `naming form ${names[target]}`,
          quote_score: 1,
          confidence: 0.5,
          needs_review: true,
          issues: [],
        })),
      },
    );
    candidateIds = staged.candidate_ids;
  }
  return { documentId, names, candidateIds };
}
