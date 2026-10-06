import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import {
  ObligationDetailView,
  assignObligation,
  assigneeText,
  changeObligationStatus,
  commentOnObligation,
  getObligation,
  memberLabel,
  type AssigneeMode,
} from "@/features/obligations";
import { newIdempotencyKey } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { TENANT_ADMIN_ROLES, hasRole } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.obligation");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string; obligationId: string }>;
}

export default async function ObligationPage({ params }: Props) {
  const { businessId, obligationId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId, obligationId });
  if (!isUuid(businessId) || !isUuid(obligationId)) notFound();
  const page = await getObligation(session, businessId, obligationId, {
    // Identity lists the tenant's users to its admins only (owners and CA admins).
    canListMembers: hasRole(session, TENANT_ADMIN_ROLES),
  });
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const { obligation, assignee } = page.value;
  const list = businessHeaderLinks(
    "owner.obligations",
    session,
    businessId,
    page.value.business.name,
    await businessFlags(session),
  );
  const members = assignee.kind === "members" ? assignee.members : [];
  const mode: AssigneeMode =
    assignee.kind === "members"
      ? {
          kind: "members",
          options: members.map((member) => ({ id: member.id, label: memberLabel(member) })),
        }
      : {
          kind: "id",
          note:
            assignee.reason === "role"
              ? t("obligation.assignee.byIdRole")
              : t("obligation.assignee.byIdUnavailable"),
        };
  return (
    <ObligationDetailView
      view={obligation}
      header={{
        crumbs: [
          ...list.crumbs,
          {
            id: SCREEN.id,
            href: hrefFor(SCREEN, { businessId, obligationId }),
            label: obligation.title,
          },
        ],
        tabs: list.tabs,
      }}
      listHref={page.value.listHref}
      viewerId={session.userId}
      actions={{
        status: changeObligationStatus,
        assign: assignObligation,
        comment: commentOnObligation,
      }}
      keys={{
        status: newIdempotencyKey(),
        assign: newIdempotencyKey(),
        comment: newIdempotencyKey(),
      }}
      assignee={{
        mode,
        text: assigneeText(obligation.assigneeId, session.userId, members),
      }}
    />
  );
}
