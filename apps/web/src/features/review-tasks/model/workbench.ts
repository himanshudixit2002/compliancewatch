import type { Ontology } from "@/entities/ontology/types";
import type { DocumentDetail } from "@/entities/pipeline/types";
import {
  RULE_VERSION_ONLY_RELATIONS,
  type RelationCandidate,
  type RulebookDocument,
} from "@/entities/rulebook/types";
import type { ReviewTaskDetail, RuleVersion, TaskDocument } from "@/entities/rule-version/types";
import type { ApiError, Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import type { Role } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import type { ServiceErrorLike } from "@/shared/ui/service-error";
import { describeSpecification, type SpecLine } from "@/shared/ui/specification";
import {
  relationField,
  type AccessView,
  type ApprovalsView,
  type ClaimView,
  type ClauseOption,
  type DecideView,
  type DraftForm,
  type EditForm,
  type EditorOntology,
  type PersonRef,
  type RelationChoice,
} from "../ui/form-shared";
import { candidatePane, type CandidatePane } from "./candidate";
import {
  dueInDaysWords,
  periodWords,
  proposalValues,
  recurrenceWords,
  versionValues,
} from "./content";
import { compare, proposalContent, versionContent, type Comparison } from "./diff";
import { historyView, type HistoryView } from "./history";
import { decisionLabel, personRef, taskKindLabel, taskStatusLabel } from "./queue";
import { sourcePane, type QuoteRef, type SourcePane } from "./source";

/**
 * The review workbench of one task, three panes and what follows them:
 *
 *   source     each document the draft rests on (a candidate task's own document first), its
 *              clauses with the cited quotes marked, the stored file and the citations
 *   candidate  a candidate task's extraction and the draft it proposes
 *   rule       the draft in words and the steps the task's state allows the signed-in analyst:
 *              claim it, draft a version from the candidate, edit the draft, decide
 *
 * then the comparisons (the proposal against the draft, the rule's previous version against
 * the draft) and the history. Who may take which step (D-061): every regulatory role claims,
 * drafts, edits, returns and rejects; approving is a reviewer's or an admin's. Drafting and
 * editing are the claimant's alone, and only a draft that is not closed is edited.
 */
export interface Session {
  userId: string;
  roles: readonly Role[];
}

export interface DraftContentView {
  title: string;
  summary: string;
  ruleLabel: string;
  regulator: string;
  level: string;
  period: string;
  recurrence: string;
  template: {
    title: string;
    steps: readonly string[];
    due: string | null;
    evidence: string;
  } | null;
  specification: SpecLine | null;
  todo: readonly string[];
  source: { instrument: string; reference: string };
}

export interface RulePane {
  claim: ClaimView;
  draft: DraftContentView | null;
  edit: EditForm | null;
  /** Why the draft cannot be edited here, when a draft exists and no edit form is offered. */
  editBlocked: string | null;
  draftForm: DraftForm | null;
  draftBlocked: string | null;
  decide: DecideView | null;
  approvals: ApprovalsView | null;
  /** The version's page, where an approved version is published (W5). */
  publishHref: string | null;
  versionHref: string | null;
}

export interface WorkbenchView {
  taskId: string;
  title: string;
  candidateTask: boolean;
  facts: {
    kind: string;
    status: string;
    statusValue: string;
    regulator: string;
    priority: number;
    opened: string;
    claimed: { by: PersonRef; at: string | null } | null;
    decision: { label: string; by: PersonRef | null; at: string | null; note: string } | null;
    version: {
      ruleVersionId: string;
      label: string;
      status: string;
      highImpact: boolean;
      closed: boolean;
      needsReview: boolean;
      href: string;
    } | null;
  };
  source: SourcePane;
  candidate: CandidatePane | null;
  rule: RulePane;
  comparisons: {
    proposal: Comparison | null;
    previous: Comparison | null;
    previousError: ServiceErrorLike | null;
  };
  history: HistoryView;
  access: AccessView;
  editorOntology: EditorOntology | null;
  ontologyError: ServiceErrorLike | null;
}

export interface WorkbenchReads {
  detail: ReviewTaskDetail;
  ontology: Result<Ontology>;
  documents: ReadonlyMap<string, Result<RulebookDocument>>;
  stored: ReadonlyMap<string, Result<DocumentDetail>>;
  /** The rule's versions, for the previous one; null when the task has no version. */
  ruleVersions: Result<RuleVersion[]> | null;
  /** For the draft form only: the open relation candidates of the candidate's document. */
  relations: Result<RelationCandidate[]> | null;
  /** For the draft form only: every rule's versions a relation may point at. */
  targets: Result<RuleVersion[]> | null;
  /** For the draft form only: the rules' keys. */
  ruleKeys: readonly string[];
  /** Claim, draft, edit and a rejection before drafting: web.admin_rulebook_writes. */
  access: AccessView;
  /** The steps that move the version's lifecycle: web.publish_actions as well (D-061). */
  lifecycle: AccessView;
}

export function errorLike(error: ApiError): ServiceErrorLike {
  return {
    message: error.message,
    status: error.status,
    requestId: error.requestId,
    problem: { detail: error.problem?.detail ?? null },
  };
}

/** The ontology the predicate editor needs, without the wording onboarding uses. */
export function editorOntology(ontology: Ontology): EditorOntology {
  return {
    attributes: ontology.attributes.map((attribute) => ({
      key: attribute.key,
      type: attribute.type,
      definition: attribute.definition,
      options: attribute.options,
    })),
    operatorsByType: ontology.operatorsByType,
  };
}

/** The documents in the order the source pane shows them: the candidate's first, then cited. */
export function sourceDocumentIds(detail: ReviewTaskDetail): string[] {
  const ids: string[] = [];
  const candidate = detail.candidate?.documentId;
  if (candidate !== undefined) ids.push(candidate);
  for (const document of detail.documents) {
    if (!ids.includes(document.documentId)) ids.push(document.documentId);
  }
  for (const citation of detail.citations) {
    if (!ids.includes(citation.documentId)) ids.push(citation.documentId);
  }
  return ids;
}

const LEVEL_WORDS: Readonly<Record<RuleVersion["level"], MessageKey>> = {
  entity: "workbench.level.entity",
  registration: "workbench.level.registration",
  location: "workbench.level.location",
};

function draftContent(version: RuleVersion, ontology: Ontology | null): DraftContentView {
  const template = version.obligationTemplate;
  return {
    title: version.title,
    summary: version.summary,
    ruleLabel: t("reviewQueue.ruleVersion", { rule: version.ruleKey, version: version.version }),
    regulator: version.regulator,
    level: t(LEVEL_WORDS[version.level]),
    period: periodWords(version.effectiveFrom, version.effectiveTo),
    recurrence: recurrenceWords(version.recurrence),
    template:
      template === null
        ? null
        : {
            title: template.title,
            steps: template.steps,
            // A recurring duty falls due as its recurrence says; days after it applies only
            // date a one-off duty.
            due: version.recurrence === null ? dueInDaysWords(template) : null,
            evidence:
              template.evidenceType === null || template.evidenceType === ""
                ? t("common.none")
                : humanise(template.evidenceType),
          },
    specification:
      version.specification === null
        ? null
        : describeSpecification(version.specification, ontology),
    todo: version.todo,
    source: { instrument: version.source.instrument, reference: version.source.reference },
  };
}

function clauseOptions(
  ids: readonly string[],
  documents: ReadonlyMap<string, Result<RulebookDocument>>,
): ClauseOption[] {
  return ids.flatMap((documentId) => {
    const read = documents.get(documentId);
    if (read === undefined || !read.ok) return [];
    const reference = read.value.externalRef;
    return read.value.clauses.map((clause) => ({
      value: clause.clauseId,
      label: t("workbench.clauseOption", {
        ref: clause.clauseRef,
        document: reference,
        start:
          Array.from(clause.text).slice(0, 60).join("") +
          (Array.from(clause.text).length > 60 ? "..." : ""),
      }),
    }));
  });
}

function versionOptionLabel(version: RuleVersion): string {
  return t("workbench.versionOption", {
    rule: version.ruleKey,
    version: version.version,
    status: humanise(version.status),
  });
}

/**
 * The relation candidates a draft may take on, as the form offers them: each open candidate of the
 * document with the versions it may point at (its rule's, when it names one; any open version
 * otherwise) and whether its kind needs one.
 */
export function relationChoices(
  relations: readonly RelationCandidate[],
  targets: readonly RuleVersion[],
): RelationChoice[] {
  const open = [...targets]
    .filter((version) => !version.closed)
    .sort((a, b) => a.ruleKey.localeCompare(b.ruleKey) || a.version - b.version);
  return relations.map((relation) => ({
    candidateId: relation.candidateId,
    label: t("workbench.relationLabel", {
      relation: humanise(relation.relation),
      target: relation.targetName,
    }),
    evidenceQuote: relation.evidenceQuote,
    needsTarget:
      (RULE_VERSION_ONLY_RELATIONS as readonly string[]).includes(relation.relation) ||
      relation.targetRuleKey !== null,
    targetOptions: open
      .filter(
        (version) => relation.targetRuleKey === null || version.ruleKey === relation.targetRuleKey,
      )
      .map((version) => ({ value: version.ruleVersionId, label: versionOptionLabel(version) })),
  }));
}

/**
 * The relation candidates a draft takes on, checked against what the form offers, read again from
 * the rulebook when the draft is sent (a crafted request could name any candidate or version):
 * each must be an open relation candidate of the candidate's document, name a version where its
 * kind needs one, and name only a version among its row's choices (D-061). The problems are keyed
 * by the rows' fields; none when every one is offered.
 */
export function checkRelations(
  sent: readonly { candidateId: string; targetRuleVersionId: string | null }[],
  offered: readonly RelationChoice[],
): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  const byId = new Map(offered.map((choice) => [choice.candidateId, choice]));
  for (const relation of sent) {
    const choice = byId.get(relation.candidateId);
    if (choice === undefined) {
      errors[relationField(relation.candidateId, "take")] = [
        t("workbench.error.relationNotOffered"),
      ];
    } else if (relation.targetRuleVersionId === null) {
      if (choice.needsTarget) {
        errors[relationField(relation.candidateId, "target")] = [
          t("workbench.error.relationTarget"),
        ];
      }
    } else if (
      !choice.targetOptions.some((option) => option.value === relation.targetRuleVersionId)
    ) {
      errors[relationField(relation.candidateId, "target")] = [
        t("workbench.error.relationTargetNotOffered"),
      ];
    }
  }
  return errors;
}

/** The version before this one of the rule, skipping closed drafts; null when there is none. */
export function previousVersion(
  versions: readonly RuleVersion[],
  current: RuleVersion,
): RuleVersion | null {
  const earlier = versions
    .filter((version) => version.version < current.version && !version.closed)
    .sort((a, b) => b.version - a.version);
  return earlier[0] ?? null;
}

function revisionOf(detail: ReviewTaskDetail): string {
  const last = detail.decisions.at(-1)?.decisionId ?? "none";
  return `${detail.version?.status ?? "undrafted"}:${detail.decisions.length}:${last}:${detail.citations.length}`;
}

function claimView(detail: ReviewTaskDetail, session: Session, access: AccessView): ClaimView {
  const task = detail.task;
  if (task.status === "decided") return { state: "decided" };
  if (task.claimedBy === null) return { state: "open", canClaim: access.allowed };
  const at = task.claimedAt === null ? null : formatDateTime(task.claimedAt);
  if (task.claimedBy === session.userId) return { state: "mine", at };
  return { state: "other", by: personRef(task.claimedBy, session.userId), at };
}

function editBlocked(detail: ReviewTaskDetail, claim: ClaimView): string | null {
  const version = detail.version;
  if (version === null) return null;
  if (claim.state === "decided") return t("workbench.edit.blockedDecided");
  if (version.closed) return t("workbench.edit.blockedClosed");
  if (version.status !== "draft") {
    return version.status === "in_review"
      ? t("workbench.edit.blockedInReview")
      : t("workbench.edit.blockedStatus", { status: humanise(version.status) });
  }
  if (claim.state === "open") return t("workbench.edit.blockedUnclaimed");
  if (claim.state === "other") return t("workbench.edit.blockedOther");
  return null;
}

/** Why the lifecycle's steps wait: the flag (or token) refusal, then what it holds back. */
function lifecycleBlocked(lifecycle: AccessView): string | null {
  return lifecycle.allowed
    ? null
    : t("workbench.decide.blockedLifecycle", { reason: lifecycle.title });
}

function decideView(
  detail: ReviewTaskDetail,
  session: Session,
  lifecycle: AccessView,
): DecideView | null {
  if (detail.task.status === "decided") return null;
  const version = detail.version;
  const candidateTask = detail.task.kind === "candidate";
  const drafted = version !== null;
  const approver = can(session, "admin.review.approve");
  const waits = lifecycleBlocked(lifecycle);
  let approveBlocked: string | null = null;
  if (!drafted) approveBlocked = t("workbench.decide.blockedNotDrafted");
  else if (version.closed) approveBlocked = t("workbench.edit.blockedClosed");
  else if (version.status !== "draft" && version.status !== "in_review") {
    approveBlocked = t("workbench.edit.blockedStatus", { status: humanise(version.status) });
  } else if (!approver) approveBlocked = t("workbench.decide.blockedRole");
  else approveBlocked = waits;
  // A rejection before drafting closes the candidate alone; once drafted it moves the version.
  const rejectBlocked = drafted ? waits : null;
  return {
    candidateTask,
    drafted,
    canApprove: approveBlocked === null,
    approveBlocked,
    canReturn: drafted && waits === null,
    returnBlocked: drafted ? waits : null,
    canReject: rejectBlocked === null,
    rejectBlocked,
    highImpact: version?.highImpact ?? false,
  };
}

function approvalsView(detail: ReviewTaskDetail, session: Session): ApprovalsView | null {
  if (detail.version === null) return null;
  const approvers = detail.approvedBy.map((userId) => personRef(userId, session.userId));
  return {
    count: approvers.length,
    required: detail.requiredApprovals,
    approvers,
    waitingForAnother: approvers.length > 0 && approvers.length < detail.requiredApprovals,
  };
}

export function workbenchView(reads: WorkbenchReads, session: Session): WorkbenchView {
  const { detail } = reads;
  const task = detail.task;
  const version = detail.version;
  const candidate = detail.candidate;
  const ontology = reads.ontology.ok ? reads.ontology.value : null;
  const documentIds = sourceDocumentIds(detail);
  const facts = new Map<string, TaskDocument>(
    detail.documents.map((document) => [document.documentId, document]),
  );
  if (candidate?.document !== null && candidate?.document !== undefined) {
    facts.set(candidate.document.documentId, candidate.document);
  }
  const quotes: QuoteRef[] = [
    ...detail.citations.map((citation) => ({ clauseId: citation.clauseId, quote: citation.quote })),
    ...(candidate?.proposed.citations ?? []).map((citation) => ({
      clauseId: citation.clauseId,
      quote: citation.quote,
    })),
  ];
  const claim = claimView(detail, session, reads.access);
  const mine = claim.state === "mine";
  const versionPage = screenById("admin.rulebook.version");
  const versionHref =
    version === null ? null : hrefFor(versionPage, { ruleVersionId: version.ruleVersionId });
  const options = clauseOptions(documentIds, reads.documents);

  let draftForm: DraftForm | null = null;
  let draftBlocked: string | null = null;
  if (candidate !== null && version === null && task.status !== "decided") {
    if (!mine) {
      draftBlocked =
        claim.state === "other"
          ? t("workbench.draft.blockedOther")
          : t("workbench.draft.blockedUnclaimed");
    } else {
      const relations = reads.relations;
      draftForm = {
        initial: proposalValues(candidate.proposed),
        ruleKey: candidate.suggestedRuleKey ?? "",
        suggestedKnown: candidate.suggestedRuleKnown,
        regulator: candidate.regulator,
        ruleKeys: [...reads.ruleKeys],
        relations:
          relations !== null && relations.ok
            ? relationChoices(
                relations.value,
                reads.targets !== null && reads.targets.ok ? reads.targets.value : [],
              )
            : [],
        relationsError:
          relations !== null && !relations.ok
            ? errorLike(relations.error)
            : reads.targets !== null && !reads.targets.ok
              ? errorLike(reads.targets.error)
              : null,
        clauseOptions: options,
        proposedCitations: candidate.proposed.citations.map((citation) => ({
          clauseRef: citation.clauseRef,
          quote: citation.quote,
        })),
        revision: revisionOf(detail),
      };
    }
  }

  const blocked = editBlocked(detail, claim);
  const edit: EditForm | null =
    version !== null && blocked === null && reads.access.allowed
      ? { initial: versionValues(version), clauseOptions: options, revision: revisionOf(detail) }
      : null;

  const previous =
    version === null || reads.ruleVersions === null || !reads.ruleVersions.ok
      ? null
      : previousVersion(reads.ruleVersions.value, version);

  return {
    taskId: task.taskId,
    title: version?.title ?? candidate?.proposed.title ?? t("workbench.untitled"),
    candidateTask: task.kind === "candidate",
    facts: {
      kind: taskKindLabel(task.kind),
      status: taskStatusLabel(task.status),
      statusValue: task.status,
      regulator: task.regulator,
      priority: task.priority,
      opened: formatDateTime(task.openedAt),
      claimed:
        task.claimedBy === null
          ? null
          : {
              by: personRef(task.claimedBy, session.userId),
              at: task.claimedAt === null ? null : formatDateTime(task.claimedAt),
            },
      decision:
        task.decision === null
          ? null
          : {
              label: decisionLabel(task.decision),
              by: task.decidedBy === null ? null : personRef(task.decidedBy, session.userId),
              at: task.decidedAt === null ? null : formatDateTime(task.decidedAt),
              note: task.note,
            },
      version:
        version === null || versionHref === null
          ? null
          : {
              ruleVersionId: version.ruleVersionId,
              label: t("reviewQueue.ruleVersion", {
                rule: version.ruleKey,
                version: version.version,
              }),
              status: version.status,
              highImpact: version.highImpact,
              closed: version.closed,
              needsReview: version.needsReview,
              href: versionHref,
            },
    },
    source: sourcePane({
      documentIds,
      candidateDocumentId: candidate?.documentId ?? null,
      facts,
      documents: reads.documents,
      stored: reads.stored,
      quotes,
      citations: detail.citations,
    }),
    candidate: candidate === null ? null : candidatePane(candidate, ontology, session.userId),
    rule: {
      claim,
      draft: version === null ? null : draftContent(version, ontology),
      edit,
      editBlocked:
        version === null ? null : (blocked ?? (reads.access.allowed ? null : reads.access.title)),
      draftForm: reads.access.allowed ? draftForm : null,
      draftBlocked: draftForm !== null && !reads.access.allowed ? reads.access.title : draftBlocked,
      decide: reads.access.allowed ? decideView(detail, session, reads.lifecycle) : null,
      approvals: approvalsView(detail, session),
      publishHref: version !== null && version.status === "approved" ? versionHref : null,
      versionHref,
    },
    comparisons: {
      proposal:
        candidate !== null && version !== null
          ? compare(proposalContent(candidate.proposed), versionContent(version), ontology, {
              title: t("workbench.diff.proposalTitle"),
              beforeLabel: t("workbench.diff.proposalLabel"),
              afterLabel: t("workbench.diff.draftLabel"),
            })
          : null,
      previous:
        previous === null || version === null
          ? null
          : compare(versionContent(previous), versionContent(version), ontology, {
              title: t("workbench.diff.previousTitle", {
                rule: previous.ruleKey,
                version: previous.version,
              }),
              beforeLabel: t("workbench.diff.previousLabel", { version: previous.version }),
              afterLabel: t("workbench.diff.draftLabel"),
            }),
      previousError:
        reads.ruleVersions !== null && !reads.ruleVersions.ok
          ? errorLike(reads.ruleVersions.error)
          : null,
    },
    history: historyView(detail.decisions, detail.tasks, task.taskId, session.userId),
    access: reads.access,
    editorOntology: ontology === null ? null : editorOntology(ontology),
    ontologyError: reads.ontology.ok ? null : errorLike(reads.ontology.error),
  };
}
