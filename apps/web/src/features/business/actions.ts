"use server";

import { idempotencyHeaders } from "@/server/api/idempotency";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { getOntology } from "@/server/ontology";
import { toActionState } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { actionSuccess, fieldFailure, type ActionState } from "@/shared/lib/action-state";
import { businessGateway } from "./gateway";
import { parseBusinessForm } from "./model/business-form";
import { businessStepResult, type BusinessStepResult } from "./model/prefill";

/**
 * The business step's server action. It runs the screen's gate again (the proxy never sees an
 * action), checks the form's shape, and creates the business with `POST /v1/businesses`,
 * carrying the Idempotency-Key the form was rendered with, so a double submit records one
 * business and gets the first answer back. The answer (new or already on file, what the GSTIN
 * lookup returned, the first question) becomes the result panel; the ontology words its values,
 * and when the ontology cannot be read the raw values are shown instead of failing a business
 * that was created.
 */
export async function createBusiness(
  _state: ActionState<BusinessStepResult>,
  formData: FormData,
): Promise<ActionState<BusinessStepResult>> {
  const session = await requireScreenSession(screenById("owner.onboarding.business"));
  const parsed = parseBusinessForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);

  const created = await businessGateway({ session }).create(
    parsed.value,
    idempotencyHeaders(formData, "profile.create-business"),
  );
  if (!created.ok) return toActionState(created);

  const ontology = await getOntology();
  const businessId = created.value.business.id;
  afterMutation({ paths: [hrefFor(screenById("owner.businesses"))] });
  return actionSuccess(
    businessStepResult(created.value, parsed.value.gstin, ontology.ok ? ontology.value : null, {
      questions: hrefFor(screenById("owner.onboarding.questions"), { businessId }),
      done: hrefFor(screenById("owner.onboarding.done"), { businessId }),
    }),
  );
}
