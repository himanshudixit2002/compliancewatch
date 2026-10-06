"use server";

import { isProblemOf } from "@/entities/problem/mappers";
import { requireScreenSession } from "@/server/dal";
import { getOntology } from "@/server/ontology";
import { toActionState } from "@/server/result";
import { can } from "@/shared/config/permissions";
import { screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { actionFailure, actionSuccess, type ActionState } from "@/shared/lib/action-state";
import { impactExplorerGateway } from "./gateway";
import { formValues, parseDryRunForm } from "./model/form";
import { dryRunView } from "./model/report";
import { TOO_LARGE, type DryRunAnswer } from "./ui/dry-run-shared";

/**
 * Runs a dry run: the tool's gate again (an admin only, as the engine's route rules: a dry run
 * reads every tenant's profiles), the form's shape, then the engine. Nothing is stored but the
 * engine's audit entry. The report comes back worded, the attributes named with the ontology's
 * meaning (read once per request, cached an hour; without it the keys stand alone). A scope wider
 * than the engine's maximum is its 422 `applicability-dry-run-too-large`, answered with the way
 * to narrow it.
 */
const SCREEN = screenById("admin.impact");

export async function runDryRun(
  _state: ActionState<DryRunAnswer>,
  formData: FormData,
): Promise<ActionState<DryRunAnswer>> {
  const session = await requireScreenSession(SCREEN);
  if (!can(session, "admin.impact")) return actionFailure(t("impact.error.adminOnly"));
  const values = formValues(formData);
  const parsed = parseDryRunForm(values);
  if (!parsed.ok) return { status: "error", fieldErrors: parsed.fieldErrors };
  const result = await impactExplorerGateway().dryRun(parsed.request);
  if (!result.ok) {
    const state = toActionState<DryRunAnswer>({ ok: false, error: result.error });
    if (state.status === "error" && isProblemOf(result.error.problem, TOO_LARGE)) {
      return { ...state, formErrors: [...(state.formErrors ?? []), t("impact.error.tooLarge")] };
    }
    return state;
  }
  const ontology = await getOntology();
  const report = dryRunView(result.value, ontology.ok ? ontology.value : null);
  return actionSuccess({ values, report }, t("impact.report.done"));
}
