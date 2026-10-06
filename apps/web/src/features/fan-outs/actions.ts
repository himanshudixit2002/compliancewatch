"use server";

import { z } from "zod";
import { rulebookWorkflow } from "@/server/api/rulebook-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState, type Result } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import { fanOutsGateway } from "./gateway";
import {
  CONTROL_FIELDS,
  REASON_MAX_LENGTH,
  REASON_MIN_LENGTH,
  type ControlResult,
} from "./ui/controls-shared";

/**
 * The fan-out controls: the global hold, a run's pause, resume and cancel, and the rollback of a
 * published version through the rulebook's withdraw. Each runs the page's gate again (the proxy
 * is not on an action's path), refuses anyone but an admin (`admin.fan_outs.control`, D-049)
 * before any request, checks the reason's shape (the engine and the rulebook own the rules and
 * keep the reason in their audit logs), and on success renders the fan-out pages again. The
 * rollback goes through `server/api/rulebook-write.ts`, behind `web.publish_actions` and the
 * review token, with the session's user as the actor.
 */
const LIST = screenById("admin.fan-outs");
const PAGE = screenById("admin.fan-out");

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function adminOnly(): ActionState<ControlResult> {
  return actionFailure(t("fanOuts.error.adminOnly"));
}

function unknownVersion(): ActionState<ControlResult> {
  return actionFailure(t("fanOuts.error.unknownVersion"));
}

/** A reason of 10 to 2000 characters once trimmed, or the message for its field. */
function reasonOf(formData: FormData, required: boolean): { reason: string } | { error: string } {
  const reason = text(formData, CONTROL_FIELDS.reason).trim();
  if (reason.length > REASON_MAX_LENGTH) {
    return { error: t("fanOuts.error.reasonTooLong", { max: REASON_MAX_LENGTH }) };
  }
  if (required && reason.length < REASON_MIN_LENGTH) {
    return { error: t("fanOuts.error.reasonTooShort", { min: REASON_MIN_LENGTH }) };
  }
  return { reason };
}

function reasonRefused(error: string): ActionState<ControlResult> {
  return fieldFailure({ [CONTROL_FIELDS.reason]: [error] });
}

/** After a change: the list and the version's page render again from the engine's state. */
function refresh(ruleVersionId: string | null): void {
  const paths = [hrefFor(LIST)];
  if (ruleVersionId !== null) paths.push(hrefFor(PAGE, { ruleVersionId }));
  afterMutation({ paths });
}

function answered<T>(
  result: Result<T>,
  ruleVersionId: string | null,
  message: string,
): ActionState<ControlResult> {
  if (!result.ok) return toActionState<ControlResult>({ ok: false, error: result.error });
  refresh(ruleVersionId);
  return actionSuccess({ message }, message);
}

/**
 * Sets or releases the global hold, with the reason the engine keeps (required both ways here:
 * releasing restarts every held run). Bound to the version whose page holds the form, or null
 * on the list.
 */
export async function setFanOutHold(
  ruleVersionId: string | null,
  _state: ActionState<ControlResult>,
  formData: FormData,
): Promise<ActionState<ControlResult>> {
  const session =
    ruleVersionId === null
      ? await requireScreenSession(LIST)
      : await requireScreenSession(PAGE, { ruleVersionId });
  if (!can(session, "admin.fan_outs.control")) return adminOnly();
  if (ruleVersionId !== null && !isHexUuid(ruleVersionId)) return unknownVersion();
  const parsed = z.enum(["on", "off"]).safeParse(text(formData, CONTROL_FIELDS.hold));
  if (!parsed.success) return actionFailure(t("fanOuts.error.badControl"));
  const reason = reasonOf(formData, true);
  if ("error" in reason) return reasonRefused(reason.error);
  const held = parsed.data === "on";
  const result = await fanOutsGateway().setHold(held, reason.reason);
  return answered(
    result,
    ruleVersionId?.toLowerCase() ?? null,
    held ? t("fanOuts.hold.setDone") : t("fanOuts.hold.releasedDone"),
  );
}

const CONTROL_DONE: Readonly<Record<"pause" | "resume" | "cancel", MessageKey>> = {
  pause: "fanOut.control.pauseDone",
  resume: "fanOut.control.resumeDone",
  cancel: "fanOut.control.cancelDone",
};

/** Pauses, resumes or cancels one run; pausing and cancelling need a reason. */
export async function controlFanOut(
  ruleVersionId: string,
  _state: ActionState<ControlResult>,
  formData: FormData,
): Promise<ActionState<ControlResult>> {
  const session = await requireScreenSession(PAGE, { ruleVersionId });
  if (!can(session, "admin.fan_outs.control")) return adminOnly();
  if (!isHexUuid(ruleVersionId)) return unknownVersion();
  const parsed = z
    .enum(["pause", "resume", "cancel"])
    .safeParse(text(formData, CONTROL_FIELDS.control));
  if (!parsed.success) return actionFailure(t("fanOuts.error.badControl"));
  const control = parsed.data;
  const reason = reasonOf(formData, control !== "resume");
  if ("error" in reason) return reasonRefused(reason.error);
  const id = ruleVersionId.toLowerCase();
  const gateway = fanOutsGateway();
  const result =
    control === "pause"
      ? await gateway.pause(id, reason.reason)
      : control === "resume"
        ? await gateway.resume(id, reason.reason)
        : await gateway.cancel(id, reason.reason);
  return answered(result, id, t(CONTROL_DONE[control]));
}

/**
 * Rolls a published version back: the rulebook withdraws it with the reason, the engine then
 * cancels its fan-out if it is still running, and the obligation service closes the obligations
 * it made. Behind web.publish_actions and the review token, checked by the workflow port.
 */
export async function rollBackVersion(
  ruleVersionId: string,
  _state: ActionState<ControlResult>,
  formData: FormData,
): Promise<ActionState<ControlResult>> {
  const session = await requireScreenSession(PAGE, { ruleVersionId });
  if (!can(session, "admin.fan_outs.control")) return adminOnly();
  if (!isHexUuid(ruleVersionId)) return unknownVersion();
  const reason = reasonOf(formData, true);
  if ("error" in reason) return reasonRefused(reason.error);
  const id = ruleVersionId.toLowerCase();
  const workflow = await rulebookWorkflow({ session });
  const result = await workflow.withdraw(id, reason.reason);
  if (result.ok) {
    afterMutation({
      paths: [
        hrefFor(screenById("admin.rulebook.version"), { ruleVersionId: id }),
        hrefFor(screenById("admin.rulebook.versions")),
      ],
    });
  }
  return answered(result, id, t("fanOut.rollback.done"));
}
