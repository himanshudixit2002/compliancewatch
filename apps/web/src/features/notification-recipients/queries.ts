import "server-only";

import { randomUUID } from "node:crypto";
import type { Recipient } from "@/entities/notification/types";
import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { err, ok, webError, type Result } from "@/server/result";
import type { TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import { recipientsGateway } from "./gateway";
import {
  BUSINESS_CHOICES,
  RECIPIENTS_PAGE_SIZE,
  recipientsPageView,
  type RecipientsPageView,
} from "./model/page";

/**
 * The recipients page's read: the tenant's businesses (one page, by name), the templates (the
 * languages offered), the recipients that follow the chosen business, and the recipient being
 * changed. A business the tenant does not have is not found; a recipient to change that is gone
 * leaves the page with the add form and a note.
 */
export interface RecipientsPageQuery {
  /** The business to show; the first by name when absent. */
  businessId?: string;
  /** The recipient to change. */
  editId?: string;
}

export interface RecipientsQueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
  newRecipientId?: () => string;
}

export async function getRecipientsPage(
  session: ClientPrincipal & { tenantKind: TenantKind },
  query: RecipientsPageQuery,
  pageHref: string,
  deps: RecipientsQueryDeps = {},
): Promise<Result<RecipientsPageView>> {
  const gateway = recipientsGateway({ session, fetchImpl: deps.fetchImpl });
  const [businesses, templates] = await Promise.all([
    gateway.businesses(BUSINESS_CHOICES),
    gateway.templates(),
  ]);
  if (!businesses.ok) return businesses;
  if (!templates.ok) return templates;
  const choices = businesses.value.items;
  const chosen =
    query.businessId === undefined
      ? choices[0]
      : choices.find((business) => business.id === query.businessId);
  if (query.businessId !== undefined && chosen === undefined) {
    return err(webError("not_found", "web-business-not-found", t("recipients.businessNotFound")));
  }
  const selected = chosen === undefined ? null : { id: chosen.id, name: chosen.name };
  let recipients: readonly Recipient[] = [];
  let moreRecipients = false;
  let editing: Recipient | null = null;
  let editMissing = false;
  if (selected !== null) {
    const [list, edit] = await Promise.all([
      gateway.list(selected.id, RECIPIENTS_PAGE_SIZE),
      query.editId === undefined ? Promise.resolve(null) : gateway.get(query.editId),
    ]);
    if (!list.ok) return list;
    recipients = list.value.items;
    moreRecipients = list.value.nextCursor !== null;
    if (edit !== null) {
      if (edit.ok) editing = edit.value;
      else if (edit.error.kind === "not_found") editMissing = true;
      else return err(edit.error);
    }
  }
  return ok(
    recipientsPageView({
      tenantKind: session.tenantKind,
      businesses: choices,
      moreBusinesses: businesses.value.nextCursor !== null,
      selected,
      recipients,
      moreRecipients,
      templates: templates.value,
      editing,
      editMissing,
      newRecipientId: (deps.newRecipientId ?? randomUUID)(),
      pageHref,
    }),
  );
}
