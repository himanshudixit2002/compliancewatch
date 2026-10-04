"use server";

import { isProblemOf } from "@/entities/problem/mappers";
import type { CitationInput } from "@/entities/rule-version/types";
import { rulebookWorkflow } from "@/server/api/rulebook-write";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { toActionProblem, toActionState, type ApiError } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, type ActionState } from "@/shared/lib/action-state";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ruleVersionsGateway } from "./gateway";
import {
  CLAUSE_NOT_STORED,
  NOT_VERIFIED,
  citationsResult,
  failuresByRow,
  parseCitationsForm,
  quoteFailures,
  unknownClauses,
} from "./model/citations-form";
import { versionHref } from "./model/version-list";
import { parseStepForm, stepResult } from "./model/workflow";
import { citationField, type CitationsResult } from "./ui/citations-shared";
import type { StepResult } from "./ui/workflow-shared";

const SCREEN = screenById("admin.rulebook.version");

function invalidVersion<T>(): ActionState<T> {
  return actionFailure(t("ruleVersion.workflow.unknownVersion"));
}

/** After a change: the version page and the list render again from the rulebook's state. */
function refresh(ruleVersionId: string): void {
  afterMutation({
    paths: [versionHref(ruleVersionId), hrefFor(screenById("admin.rulebook.versions"))],
  });
}

/**
 * A refused save, with each refusal on the row it belongs to: the rows whose clause the rulebook
 * does not hold, and the rows whose quote it could not find in its clause (matched by the clause
 * reference and document the rulebook names, read from the clause route). Every failure line the
 * rulebook gave is listed under its problem as well.
 */
async function refusedCitations(
  error: ApiError,
  sent: readonly CitationInput[],
): Promise<ActionState<CitationsResult>> {
  const state = toActionState<CitationsResult>({ ok: false, error });
  if (state.status !== "error") return state;
  const fieldErrors: Record<string, readonly string[]> = { ...state.fieldErrors };
  const detail = error.problem?.detail ?? undefined;
  const failures: string[] = [];
  if (isProblemOf(error.problem, CLAUSE_NOT_STORED)) {
    const unknown = new Set(unknownClauses(detail ?? undefined));
    sent.forEach((row, index) => {
      if (unknown.has(row.clauseId)) {
        fieldErrors[citationField(index, "clause_id")] = [t("citations.form.clauseUnknown")];
      }
    });
  }
  if (isProblemOf(error.problem, NOT_VERIFIED)) {
    failures.push(...quoteFailures(detail ?? undefined));
    const gateway = ruleVersionsGateway();
    const clauses = await Promise.all(sent.map((row) => gateway.clause(row.clauseId)));
    const rows = clauses.map((read) =>
      read.ok
        ? { clauseRef: read.value.clauseRef, documentId: read.value.documentId }
        : { clauseRef: "", documentId: "" },
    );
    for (const [index, reason] of Object.entries(failuresByRow(failures, rows))) {
      fieldErrors[citationField(Number(index), "quote")] = [
        t("citations.form.quoteNotFound", { reason }),
      ];
    }
  }
  return {
    status: "error",
    problem: toActionProblem(error),
    ...(Object.keys(fieldErrors).length > 0 ? { fieldErrors } : {}),
    ...(failures.length > 0 ? { formErrors: failures } : {}),
  };
}

/**
 * Cites clauses for a draft version: the tool's gate again, the rows' shape, then the rulebook,
 * which stores all of them or none (behind web.publish_actions and the review token, through
 * server/api/rulebook-write.ts). On success the page renders again with the stored citations.
 */
export async function saveCitations(
  ruleVersionId: string,
  _state: ActionState<CitationsResult>,
  formData: FormData,
): Promise<ActionState<CitationsResult>> {
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) return invalidVersion();
  const parsed = parseCitationsForm(formData);
  if (!parsed.ok) {
    return {
      status: "error",
      ...(Object.keys(parsed.fieldErrors).length > 0 ? { fieldErrors: parsed.fieldErrors } : {}),
      ...(parsed.formErrors.length > 0 ? { formErrors: parsed.formErrors } : {}),
    };
  }
  const workflow = await rulebookWorkflow({ session });
  const result = await workflow.cite(ruleVersionId.toLowerCase(), parsed.citations);
  if (!result.ok) return refusedCitations(result.error, parsed.citations);
  refresh(ruleVersionId.toLowerCase());
  const value = citationsResult(result.value, parsed.citations);
  return {
    status: "ok",
    value,
    message: t("citations.saved", { added: value.added, unchanged: value.unchanged }),
  };
}

/**
 * One step of the publish workflow: the gate again, the step and its note (a reason for return
 * and withdraw), then the rulebook, with the session's user as the actor and never a synthetic
 * approval. Any refusal comes back with the rulebook's problem for the panel to show next to the
 * step; on success the page renders again in the version's new status.
 */
export async function takeStep(
  ruleVersionId: string,
  _state: ActionState<StepResult>,
  formData: FormData,
): Promise<ActionState<StepResult>> {
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) return invalidVersion();
  const parsed = parseStepForm(formData);
  if (!parsed.ok) return { status: "error", fieldErrors: parsed.fieldErrors };
  const id = ruleVersionId.toLowerCase();
  const workflow = await rulebookWorkflow({ session });
  const result =
    parsed.step === "submit"
      ? await workflow.submit(id, { highImpact: parsed.highImpact, note: parsed.note })
      : parsed.step === "approve"
        ? await workflow.approve(id, parsed.note)
        : parsed.step === "publish"
          ? await workflow.publish(id, parsed.note)
          : parsed.step === "return"
            ? await workflow.returnToDraft(id, parsed.note)
            : await workflow.withdraw(id, parsed.note);
  if (!result.ok) return toActionState<StepResult>({ ok: false, error: result.error });
  refresh(id);
  return { status: "ok", value: stepResult(parsed.step, result.value) };
}
