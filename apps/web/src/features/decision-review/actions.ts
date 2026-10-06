"use server";

import { z } from "zod";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";
import { decisionReviewGateway } from "./gateway";
import { NOTE_MAX_LENGTH, RESOLVE_FIELDS, type ResolveResult } from "./ui/resolve-shared";

/**
 * Settles one review item of the looked-up tenant: the screen's gate again, a reviewer or an
 * admin (`admin.decisions.resolve`; an analyst reads only, as the engine's Resolver rules), the
 * resolution and the note's shape, then the engine, which records the session's user as the
 * reviewer (`resolved_by`, never a form field) and audits the note as the reason. applies and
 * not_applicable append a decision the obligation service acts on; dismiss appends nothing.
 */
const SCREEN = screenById("admin.decisions");

const FORM = z.object({
  resolution: z.enum(["applies", "not_applicable", "dismiss"]),
  note: z.string().trim().min(1).max(NOTE_MAX_LENGTH),
});

const DONE: Readonly<Record<"applies" | "not_applicable" | "dismiss", MessageKey>> = {
  applies: "decisions.resolve.appliesDone",
  not_applicable: "decisions.resolve.notApplicableDone",
  dismiss: "decisions.resolve.dismissDone",
};

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export async function resolveReviewItem(
  tenantId: string,
  itemId: string,
  _state: ActionState<ResolveResult>,
  formData: FormData,
): Promise<ActionState<ResolveResult>> {
  const session = await requireScreenSession(SCREEN);
  if (!can(session, "admin.decisions.resolve")) {
    return actionFailure(t("decisions.resolve.reviewerOnly"));
  }
  if (!isUuid(tenantId) || !isUuid(itemId)) return actionFailure(t("decisions.resolve.badIds"));
  const parsed = FORM.safeParse({
    resolution: text(formData, RESOLVE_FIELDS.resolution),
    note: text(formData, RESOLVE_FIELDS.note),
  });
  if (!parsed.success) {
    const errors: Record<string, string[]> = {};
    for (const issue of parsed.error.issues) {
      const field = String(issue.path[0]);
      errors[field] = [
        field === RESOLVE_FIELDS.resolution
          ? t("decisions.resolve.pickOne")
          : t("decisions.resolve.noteLength", { max: NOTE_MAX_LENGTH }),
      ];
    }
    return fieldFailure(errors);
  }
  const result = await decisionReviewGateway({ session, tenantId }).resolve(
    itemId,
    parsed.data,
    session.userId,
  );
  if (!result.ok) return toActionState<ResolveResult>({ ok: false, error: result.error });
  afterMutation({ paths: [hrefFor(SCREEN)] });
  const message = t(DONE[parsed.data.resolution]);
  return actionSuccess({ message }, message);
}
