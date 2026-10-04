import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, serviceUrl } from "./fixtures";

/**
 * Reads of the rulebook the rulebook specs compare the pages with, straight from the service the
 * stack runs (`make web-stack` starts it with the seed calendar's drafts; `make web-seed`
 * registers the recorded notification). Nothing here writes: every change a spec makes goes
 * through the web app as a signed-in analyst of the fake sign-in.
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
