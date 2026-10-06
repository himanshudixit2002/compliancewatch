import "server-only";

import type { RelationCandidate } from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { rulebookWriteAccess, type WriteAccess } from "@/server/api/rulebook-write";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { err, mapResult, ok, type ApiError, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { relationReviewGateway } from "./gateway";
import {
  candidateFacts,
  evidenceOf,
  lookupOrder,
  needsTargetVersion,
  predecessorOf,
  versionOptions,
  type CandidateFacts,
  type Evidence,
} from "./model/candidate";
import {
  CANDIDATE_PAGE_SIZE,
  candidateQueueView,
  type CandidateFilter,
  type CandidateQueueView,
} from "./model/queue";
import type { RelationReviewPort } from "./ports";
import type { AccessView, VersionOption } from "./ui/decision-shared";

/**
 * The relation candidate pages' reads: a page of the queue (one candidate more than a page is
 * asked for, so the view knows whether another follows), and one candidate with its evidence
 * clause, whether the session may decide it, and, while it is open and may be decided, the
 * versions an approval can start from and point at (every rule's versions, read in parallel).
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export async function getCandidateQueue(
  filter: CandidateFilter,
  deps: QueryDeps = {},
): Promise<Result<CandidateQueueView>> {
  const candidates = await relationReviewGateway(deps).candidates({
    status: filter.status,
    documentId: filter.documentId,
    after: filter.after,
    limit: CANDIDATE_PAGE_SIZE + 1,
  });
  return mapResult(candidates, (value) =>
    candidateQueueView(hrefFor(screenById("admin.rulebook.relations")), filter, value),
  );
}

/**
 * One candidate by its id: one row after the id just before it, in each status until it turns
 * up (the address's status first). Null when no status holds it.
 */
export async function findCandidate(
  port: RelationReviewPort,
  candidateId: string,
  statusHint?: string,
): Promise<Result<RelationCandidate | null>> {
  const after = predecessorOf(candidateId);
  for (const status of lookupOrder(statusHint)) {
    const page = await port.candidates({ status, documentId: null, after, limit: 1 });
    if (!page.ok) return page;
    const found = page.value[0];
    if (found !== undefined && found.candidateId === candidateId) return ok(found);
  }
  return ok(null);
}

function accessView(access: WriteAccess): AccessView {
  if (access.allowed) return { allowed: true };
  const detail = access.error.problem?.detail ?? undefined;
  return {
    allowed: false,
    title: access.error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
  };
}

/** Every rule's versions; a rule that went away between the two reads is skipped. */
async function everyVersion(port: RelationReviewPort): Promise<Result<RuleVersion[]>> {
  const rules = await port.rules();
  if (!rules.ok) return rules;
  const versions = await Promise.all(rules.value.map((rule) => port.versionsOf(rule.ruleKey)));
  const all: RuleVersion[] = [];
  for (const result of versions) {
    if (result.ok) all.push(...result.value);
    else if (result.error.kind !== "not_found") return err(result.error);
  }
  return ok(all);
}

export interface CandidatePage {
  facts: CandidateFacts;
  evidence: Evidence;
  /** The clause read failed: the page shows the quote alone with this error. */
  evidenceError: ApiError | null;
  access: AccessView;
  /** Approving needs the affected version (see needsTargetVersion). */
  needsTarget: boolean;
  /** The approve form's choices; null while the candidate is closed or may not be decided. */
  options: { from: VersionOption[]; target: VersionOption[] } | null;
  /** The versions could not be read, so the approve form cannot offer them. */
  optionsError: ApiError | null;
}

export async function getCandidatePage(
  session: ClientPrincipal,
  candidateId: string,
  statusHint: string | undefined,
  deps: QueryDeps = {},
): Promise<Result<CandidatePage | null>> {
  const port = relationReviewGateway(deps);
  const found = await findCandidate(port, candidateId, statusHint);
  if (!found.ok) return found;
  const candidate = found.value;
  if (candidate === null) return ok(null);
  const [clause, access] = await Promise.all([
    port.clause(candidate.evidenceClauseId),
    rulebookWriteAccess({ session, fetchImpl: deps.fetchImpl }),
  ]);
  const offered = candidate.status === "open" && access.allowed;
  const versions = offered ? await everyVersion(port) : null;
  return ok({
    facts: candidateFacts(candidate),
    evidence: evidenceOf(candidate, clause.ok ? clause.value : null),
    evidenceError: clause.ok ? null : clause.error,
    access: accessView(access),
    needsTarget: needsTargetVersion(candidate),
    options:
      versions !== null && versions.ok
        ? versionOptions(versions.value, candidate.targetRuleKey)
        : null,
    optionsError: versions !== null && !versions.ok ? versions.error : null,
  });
}
