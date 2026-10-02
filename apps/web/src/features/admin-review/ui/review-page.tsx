import { Card, EmptyState, Skeleton } from "@compliancewatch/ui";
import type { ApiError } from "@/server/result";
import { rulebookReviewReads } from "@/server/api/rulebook-read";
import { rulebookWriteAccess } from "@/server/api/rulebook-write";
import { requireScreenSession, sessionForRender } from "@/server/dal";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { decideEntityGroup, decideCandidate } from "../actions";
import { EntityDecisionForm } from "./entity-decision-form";
import { RelationDecisionForm } from "./relation-decision-form";
import { DecisionReceipt } from "./decision-receipt";

const REVIEW_SCREEN = screenById("admin.review");

interface EntityGroupView {
  entityType: string;
  proposedName: string;
  openCount: number;
}

interface RelationCandidateView {
  candidateId: string;
  documentId: string;
  relation: string;
  targetType: string;
  targetName: string;
  evidenceQuote: string;
}

function mapEntityGroup(g: { entity_type: string; proposed_name: string; open_count: number }): EntityGroupView {
  return { entityType: g.entity_type, proposedName: g.proposed_name, openCount: g.open_count };
}

function mapCandidate(c: { candidate_id: string; document_id: string; relation: string; target_type: string; target_name: string; evidence_quote: string }): RelationCandidateView {
  return {
    candidateId: c.candidate_id,
    documentId: c.document_id,
    relation: c.relation,
    targetType: c.target_type,
    targetName: c.target_name,
    evidenceQuote: c.evidence_quote,
  };
}

export async function ReviewPage() {
  const session = await requireScreenSession(REVIEW_SCREEN);
  const sessionView = await sessionForRender();
  const access = await rulebookWriteAccess({ session });
  const reads = rulebookReviewReads();

  const [entitiesRaw, candidatesRaw] = await Promise.all([
    reads.listEntityGroups({ session, pending: true }),
    reads.listRelationCandidates({ session, pending: true }),
  ]);

  const entities: EntityGroupView[] = entitiesRaw.ok ? entitiesRaw.value.map(mapEntityGroup) : [];
  const candidates: RelationCandidateView[] = candidatesRaw.ok
    ? candidatesRaw.value.map(mapCandidate)
    : [];
  const entitiesError: ApiError | undefined = entitiesRaw.ok ? undefined : entitiesRaw.error;
  const candidatesError: ApiError | undefined = candidatesRaw.ok ? undefined : candidatesRaw.error;

  const displayName = sessionView === null ? null : (sessionView.displayName ?? sessionView.userId);
  const roles = sessionView === null ? [] : sessionView.roles;

  return (
    <div className="flex flex-col gap-8" data-slot="admin-review-page">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">{t("review.intro")}</h1>
        <p className="text-sm text-fg-muted">{t("review.entityGroups.heading")}</p>
      </header>

      {access.allowed ? null : (
        <DecisionReceipt
          tone="warning"
          title={access.error.message}
          detail={access.error.problem?.detail ?? undefined}
        />
      )}

      {displayName === null ? null : (
        <DecisionReceipt
          tone="info"
          title={`Acting as ${displayName}`}
          detail={`Roles: ${roles.join(", ")}`}
        />
      )}

      <section className="flex flex-col gap-4" aria-labelledby="entity-groups-heading">
        <h2 id="entity-groups-heading" className="text-lg font-medium">
          {t("review.entityGroups.heading")}
        </h2>
        {entitiesError !== undefined ? (
          <DecisionReceipt
            tone="error"
            title={entitiesError.problem?.title ?? entitiesError.message}
            detail={entitiesError.problem?.detail == null ? undefined : entitiesError.problem.detail}
          />
        ) : entities.length === 0 ? (
          <EmptyState title={t("review.entityGroups.empty")} />
        ) : (
          <ul className="grid gap-4">
            {entities.map((group) => (
              <li key={`${group.entityType}:${group.proposedName}`}>
                <Card className="flex flex-col gap-4 p-4">
                  <header className="flex flex-col gap-1">
                    <p className="text-sm font-medium">{group.entityType}</p>
                    <p className="text-base">{group.proposedName}</p>
                  </header>
                  <EntityDecisionForm
                    action={decideEntityGroup}
                    entityType={group.entityType}
                    proposedName={group.proposedName}
                  />
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-4" aria-labelledby="relation-candidates-heading">
        <h2 id="relation-candidates-heading" className="text-lg font-medium">
          {t("review.relations.heading")}
        </h2>
        {candidatesError !== undefined ? (
          <DecisionReceipt
            tone="error"
            title={candidatesError.problem?.title ?? candidatesError.message}
            detail={candidatesError.problem?.detail == null ? undefined : candidatesError.problem.detail}
          />
        ) : candidates.length === 0 ? (
          <EmptyState title={t("review.relations.empty")} />
        ) : (
          <ul className="grid gap-4">
            {candidates.map((c) => (
              <li key={c.candidateId}>
                <Card className="flex flex-col gap-4 p-4">
                  <header className="flex flex-col gap-1">
                    <p className="text-sm font-medium">
                      {c.relation} → {c.targetType} {c.targetName}
                    </p>
                    <p className="text-xs text-fg-muted">{c.documentId}</p>
                  </header>
                  <RelationDecisionForm
                    action={decideCandidate}
                    candidateId={c.candidateId}
                    relation={c.relation}
                    evidenceQuote={c.evidenceQuote}
                  />
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export function ReviewPageSkeleton() {
  return (
    <div className="flex flex-col gap-8" data-slot="admin-review-skeleton">
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}