"use server";

import { z } from "zod";
import { idempotencyHeaders } from "@/server/api/idempotency";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionState, type Result } from "@/server/result";
import type { Replayable } from "@/server/api/idempotency";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionSuccess, fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";
import { obligationsGateway } from "./gateway";
import { readMonth } from "./model/calendar";
import { findFirstObligation, getCalendar } from "./queries";
import type { CalendarMonthAnswer } from "./ui/calendar-shared";
import {
  ASSIGN_TO_ME,
  ASSIGN_TO_NOBODY,
  TEXT_MAX_LENGTH,
  TRACKING_FIELDS,
  WAIVER_MIN_LENGTH,
  type FirstObligationState,
  type TrackingResult,
} from "./ui/tracking-shared";

/**
 * The obligation page's writes: start, complete or waive it, give it to someone, comment on it.
 * Each runs the screen's gate again (the proxy is not on an action's path), checks the form's
 * shape (the service owns the rules), sends the Idempotency-Key the page rendered into the form,
 * and on success renders the obligation, the list and the calendar again. A repeated request
 * with the same key gets the service's first answer back; the form says so instead of claiming
 * a second change. The poll of the onboarding summary asks for the business's first obligation.
 */
const SCREEN = screenById("owner.obligation");

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

async function gate(formData: FormData) {
  const businessId = text(formData, TRACKING_FIELDS.businessId);
  const obligationId = text(formData, TRACKING_FIELDS.obligationId);
  const session = await requireScreenSession(SCREEN, { businessId, obligationId });
  return { session, businessId, obligationId };
}

function idsRefused(): ActionState<TrackingResult> {
  return fieldFailure({ [TRACKING_FIELDS.obligationId]: [t("obligation.form.badIds")] });
}

function refreshPages(businessId: string, obligationId: string): void {
  afterMutation({
    paths: [
      hrefFor(SCREEN, { businessId, obligationId }),
      hrefFor(screenById("owner.obligations"), { businessId }),
      hrefFor(screenById("owner.calendar"), { businessId }),
    ],
  });
}

function answered<T>(
  result: Result<Replayable<T>>,
  businessId: string,
  obligationId: string,
  message: (value: T) => string,
): ActionState<TrackingResult> {
  if (!result.ok) return toActionState(result);
  refreshPages(businessId, obligationId);
  const { value, replayed } = result.value;
  const said = replayed ? `${message(value)} ${t("obligation.form.replayed")}` : message(value);
  return actionSuccess({ message: said, replayed }, said);
}

const STATUS_FORM = z.object({
  action: z.enum(["start", "complete", "waive"]),
  reason: z.string().max(TEXT_MAX_LENGTH),
});

const STATUS_MESSAGES = {
  start: "obligation.status.started",
  complete: "obligation.status.completed",
  waive: "obligation.status.waived",
} as const;

export async function changeObligationStatus(
  _state: ActionState<TrackingResult>,
  formData: FormData,
): Promise<ActionState<TrackingResult>> {
  const { session, businessId, obligationId } = await gate(formData);
  if (!isUuid(businessId) || !isUuid(obligationId)) return idsRefused();
  const parsed = STATUS_FORM.safeParse({
    action: text(formData, TRACKING_FIELDS.action),
    reason: text(formData, TRACKING_FIELDS.reason),
  });
  if (!parsed.success) {
    return fieldFailure({ [TRACKING_FIELDS.reason]: [t("obligation.form.badStatus")] });
  }
  const { action, reason } = parsed.data;
  if (action === "waive" && reason.trim().length < WAIVER_MIN_LENGTH) {
    return fieldFailure({
      [TRACKING_FIELDS.reason]: [t("obligation.waive.tooShort", { min: WAIVER_MIN_LENGTH })],
    });
  }
  const result = await obligationsGateway({ session }).changeStatus(
    obligationId,
    { action, reason },
    idempotencyHeaders(formData, "obligation.change-status"),
  );
  return answered(result, businessId, obligationId, () => t(STATUS_MESSAGES[action]));
}

export async function assignObligation(
  _state: ActionState<TrackingResult>,
  formData: FormData,
): Promise<ActionState<TrackingResult>> {
  const { session, businessId, obligationId } = await gate(formData);
  if (!isUuid(businessId) || !isUuid(obligationId)) return idsRefused();
  // "Give it to me" names the session's user, never an id the form carried.
  const choice = text(formData, TRACKING_FIELDS.assignTo);
  const assignee =
    choice === ASSIGN_TO_ME
      ? session.userId
      : choice === ASSIGN_TO_NOBODY
        ? ""
        : text(formData, TRACKING_FIELDS.assignee).trim().toLowerCase();
  if (assignee !== "" && !isUuid(assignee)) {
    return fieldFailure({ [TRACKING_FIELDS.assignee]: [t("obligation.assignee.notAnId")] });
  }
  const result = await obligationsGateway({ session }).assign(
    obligationId,
    assignee === "" ? null : assignee,
    idempotencyHeaders(formData, "obligation.assign"),
  );
  return answered(result, businessId, obligationId, (obligation) =>
    obligation.assigneeId === null
      ? t("obligation.assignee.cleared")
      : obligation.assigneeId === session.userId
        ? t("obligation.assignee.toYou")
        : t("obligation.assignee.given", { id: obligation.assigneeId }),
  );
}

export async function commentOnObligation(
  _state: ActionState<TrackingResult>,
  formData: FormData,
): Promise<ActionState<TrackingResult>> {
  const { session, businessId, obligationId } = await gate(formData);
  if (!isUuid(businessId) || !isUuid(obligationId)) return idsRefused();
  const body = text(formData, TRACKING_FIELDS.body).trim();
  if (body === "") {
    return fieldFailure({ [TRACKING_FIELDS.body]: [t("obligation.comments.empty")] });
  }
  if (body.length > TEXT_MAX_LENGTH) {
    return fieldFailure({
      [TRACKING_FIELDS.body]: [t("obligation.comments.tooLong", { max: TEXT_MAX_LENGTH })],
    });
  }
  const result = await obligationsGateway({ session }).comment(
    obligationId,
    body,
    idempotencyHeaders(formData, "obligation.comment"),
  );
  return answered(result, businessId, obligationId, () => t("obligation.comments.added"));
}

/**
 * The onboarding summary's poll: whether the business has an obligation yet. It reads, it never
 * writes, and it runs the summary's gate like any action.
 */
export async function checkFirstObligation(businessId: string): Promise<FirstObligationState> {
  const session = await requireScreenSession(screenById("owner.onboarding.done"), {
    businessId: String(businessId),
  });
  if (typeof businessId !== "string" || !isUuid(businessId)) {
    return { status: "error", message: t("firstObligation.badId"), correlationId: null };
  }
  return findFirstObligation(session, businessId);
}

/**
 * Another month of the calendar, for its grid: the month's obligations by due day, read as the
 * page reads them. Asked by the client grid so moving between months keeps the keyboard's place.
 */
export async function loadCalendarMonth(
  businessId: string,
  month: string,
): Promise<CalendarMonthAnswer> {
  const session = await requireScreenSession(screenById("owner.calendar"), {
    businessId: String(businessId),
  });
  if (typeof businessId !== "string" || !isUuid(businessId)) {
    return { status: "error", message: t("calendar.badBusiness"), correlationId: null };
  }
  const page = await getCalendar(session, businessId, readMonth(String(month)));
  if (!page.ok) {
    return {
      status: "error",
      message: page.error.message,
      correlationId: page.error.requestId === "" ? null : page.error.requestId,
    };
  }
  const { calendar } = page.value;
  return {
    status: "ok",
    data: {
      month: calendar.month,
      days: calendar.days,
      selected: calendar.selected,
      total: calendar.total,
      cut: calendar.cut,
    },
  };
}
