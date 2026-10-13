"use server";

import type { SessionClaims } from "@/entities/session/types";
import { afterMutation } from "@/server/cache";
import { requireMfa, requireScreenSession } from "@/server/dal";
import { isProblem, toActionState } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { teamGateway } from "./gateway";
import { parseDisableForm, parseInviteForm, parseRolesForm, type TeamScreenId } from "./model/team";

/**
 * What a tenant admin does on the team page: invite a person (their account at the identity
 * provider, then the user), change a member's roles (which revokes the member's sessions) and
 * disable a member (which ends theirs for good). Each action runs the screen's gate again
 * (the form names which of the two team screens it is on), needs the `team.manage` capability
 * and a verified second factor, and sends the session's bearer to identity, which decides:
 * 409 `identity-last-admin` and 422 `identity-role-not-allowed` come back as form errors, 402
 * `identity-seat-limit-reached` as the problem the dialog links to billing from. The reason
 * given for disabling a member goes nowhere yet: identity's route takes none (W13 sends it
 * along), and a process log is no place for what an admin wrote about a person, so the log
 * line says only that a reason of so many characters was given.
 */
async function gate(screenId: TeamScreenId): Promise<SessionClaims> {
  const screen = screenById(screenId);
  const next = hrefFor(screen);
  const session = await requireScreenSession(screen);
  await requireMfa({ next });
  if (!can(session, "team.manage")) throw new Error("team.manage is not in the screen's roles");
  return session;
}

function refresh(screenId: TeamScreenId): void {
  afterMutation({ paths: [hrefFor(screenById(screenId))] });
}

function withLastAdmin<T>(state: ActionState<T>): ActionState<T> {
  if (state.status !== "error" || state.problem === undefined) return state;
  const slug = state.problem.type.slice(state.problem.type.lastIndexOf(":") + 1);
  if (slug === "identity-last-admin") {
    return { ...state, formErrors: [t("team.error.lastAdmin")] };
  }
  if (slug === "identity-role-not-allowed") {
    return { ...state, fieldErrors: { roles: [state.problem.detail ?? state.problem.title] } };
  }
  return state;
}

export async function inviteMember(_state: ActionState, formData: FormData): Promise<ActionState> {
  const screenId = String(formData.get("screen") ?? "");
  if (screenId !== "owner.settings.team" && screenId !== "admin.team") {
    return actionFailure(t("team.form.screenUnknown"));
  }
  const session = await gate(screenId);
  const parsed = parseInviteForm(formData, session.tenantKind);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const invited = await teamGateway({ session }).invite(parsed.value);
  if (!invited.ok) {
    if (isProblem(invited.error, "identity-provider-account-exists")) {
      return fieldFailure({ contact: [t("team.error.accountExists")] });
    }
    return withLastAdmin(toActionState<undefined>({ ok: false, error: invited.error }));
  }
  refresh(screenId);
  return actionSuccess(
    undefined,
    t("team.invited", { name: invited.value.name || invited.value.email }),
  );
}

export async function changeMemberRoles(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const screenId = String(formData.get("screen") ?? "");
  if (screenId !== "owner.settings.team" && screenId !== "admin.team") {
    return actionFailure(t("team.form.screenUnknown"));
  }
  const session = await gate(screenId);
  const parsed = parseRolesForm(formData, session.tenantKind);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  const changed = await teamGateway({ session }).changeRoles(
    parsed.value.userId,
    parsed.value.roles,
  );
  if (!changed.ok)
    return withLastAdmin(toActionState<undefined>({ ok: false, error: changed.error }));
  refresh(screenId);
  return actionSuccess(undefined, t("team.rolesChanged", { name: changed.value.name }));
}

export async function disableMember(_state: ActionState, formData: FormData): Promise<ActionState> {
  const screenId = String(formData.get("screen") ?? "");
  if (screenId !== "owner.settings.team" && screenId !== "admin.team") {
    return actionFailure(t("team.form.screenUnknown"));
  }
  const session = await gate(screenId);
  const parsed = parseDisableForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);
  if (parsed.value.userId === session.userId) return actionFailure(t("team.error.self"));
  const disabled = await teamGateway({ session }).disable(parsed.value.userId);
  if (!disabled.ok)
    return withLastAdmin(toActionState<undefined>({ ok: false, error: disabled.error }));
  console.info(
    JSON.stringify({
      level: "info",
      event: "team_member_disabled",
      tenant_id: session.tenantId,
      user_id: parsed.value.userId,
      by: session.userId,
      reason_length: parsed.value.reason.length,
    }),
  );
  refresh(screenId);
  return actionSuccess(undefined, t("team.disabled", { name: disabled.value.name }));
}
