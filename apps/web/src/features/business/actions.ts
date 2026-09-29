"use server";

import { redirect } from "next/navigation";
import { attributeOf } from "@/entities/ontology/mappers";
import { track } from "@/server/analytics";
import { idempotencyHeaders } from "@/server/api/idempotency";
import { afterMutation } from "@/server/cache";
import { requireScreenSession } from "@/server/dal";
import { onboardingGate } from "@/server/legal";
import { can } from "@/shared/config/permissions";
import { getOntology } from "@/server/ontology";
import { toActionState, type ApiError } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import {
  actionFailure,
  actionSuccess,
  fieldFailure,
  type ActionState,
} from "@/shared/lib/action-state";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { businessGateway } from "./gateway";
import { ANSWER_FIELDS, answerFieldErrors, readAnswerForm } from "./model/answer-form";
import { parseBusinessForm } from "./model/business-form";
import { readDirectoryQuery, type DirectoryPage } from "./model/directory";
import { parseLocationForm } from "./model/location-form";
import { businessStepResult, type BusinessStepResult } from "./model/prefill";
import { skipKey } from "./model/questions";
import { parseAnswer } from "./model/values";
import { getDirectoryPage } from "./queries";
import { clearSkipList, rememberSkip } from "./skip-list";

/**
 * The business step's server action. It runs the screen's gate again (the proxy never sees an
 * action), checks the form's shape, and creates the business with `POST /v1/businesses`,
 * carrying the Idempotency-Key the form was rendered with, so a double submit records one
 * business and gets the first answer back. The answer (new or already on file, what the GSTIN
 * lookup returned, the first question) becomes the result panel; the ontology words its values,
 * and when the ontology cannot be read the raw values are shown instead of failing a business
 * that was created. While onboarding is closed (production with the terms or the privacy notice
 * still a draft) nothing is created.
 */
export async function createBusiness(
  _state: ActionState<BusinessStepResult>,
  formData: FormData,
): Promise<ActionState<BusinessStepResult>> {
  const session = await requireScreenSession(screenById("owner.onboarding.business"));
  if (onboardingGate().closed) return actionFailure(t("onboardingClosed.refused"));
  const parsed = parseBusinessForm(formData);
  if (!parsed.ok) return fieldFailure(parsed.fieldErrors);

  const created = await businessGateway({ session }).create(
    parsed.value,
    idempotencyHeaders(formData, "profile.create-business"),
  );
  if (!created.ok) return toActionState(created);

  await track(session, {
    name: "onboarding_step_completed",
    properties: {
      step: "business",
      created: created.value.created,
      looked_up: created.value.prefill?.lookedUp ?? false,
    },
  });
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

/** A refused answer: the service's problem, with its field errors on the one control. */
function answerRefused(error: ApiError): ActionState {
  const state = toActionState<undefined>({ ok: false, error });
  if (state.status !== "error") return state;
  const { value, form } = answerFieldErrors(error.fieldErrors);
  return {
    status: "error",
    ...(state.problem === undefined ? {} : { problem: state.problem }),
    ...(value.length > 0 ? { fieldErrors: { [ANSWER_FIELDS.value]: value } } : {}),
    ...(form.length > 0 ? { formErrors: form } : {}),
  };
}

/**
 * One answer from the questions step: the value with Save (state known), or Not sure or Does
 * not apply with no value, stored with `PATCH /v1/businesses/{id}` on the node the checklist
 * named (and for its year when the attribute is stated per year). A "Not sure" answer joins the
 * business's skip list so the step moves past it; any other answer leaves it. The step then
 * renders again with the next question and a note naming what was saved.
 */
export async function answerQuestion(
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const input = readAnswerForm(formData);
  if (input === null) return actionFailure(t("question.error.form"));
  const screen = screenById("owner.onboarding.questions");
  const session = await requireScreenSession(screen, { businessId: input.businessId });

  const ontology = await getOntology();
  if (!ontology.ok) return toActionState(ontology);
  const attribute = attributeOf(ontology.value, input.key);
  if (attribute === undefined) return actionFailure(t("question.error.unknown"));
  const parsed = parseAnswer(
    attribute,
    { state: input.state, values: input.values },
    { asOfFy: input.asOfFy, nodeId: input.nodeId },
  );
  if (!parsed.ok) return fieldFailure({ [ANSWER_FIELDS.value]: [parsed.error] });

  const updated = await businessGateway({ session }).update(input.businessId, {
    changes: [parsed.answer],
  });
  if (!updated.ok) return answerRefused(updated.error);
  await track(session, {
    name: "onboarding_step_completed",
    properties: { step: "question", attribute: input.key, state: parsed.answer.state },
  });

  await rememberSkip(
    input.businessId,
    skipKey(input.nodeId, input.key),
    parsed.answer.state === "unsure",
  );
  const questions = hrefFor(screen, { businessId: input.businessId });
  afterMutation({
    paths: [
      questions,
      hrefFor(screenById("owner.onboarding.done"), { businessId: input.businessId }),
    ],
  });
  redirect(withQuery(questions, { saved: input.key }));
}

/**
 * Forgets the skip list, so the questions step asks the "Not sure" questions again. A plain
 * form action: a malformed business id (only a tampered form sends one) does nothing.
 */
export async function revisitUnsure(formData: FormData): Promise<void> {
  const businessId = formData.get(ANSWER_FIELDS.businessId);
  if (typeof businessId !== "string" || !isUuid(businessId)) return;
  const screen = screenById("owner.onboarding.questions");
  await requireScreenSession(screen, { businessId });
  await clearSkipList(businessId);
  redirect(hrefFor(screen, { businessId }));
}

/**
 * One page of the businesses list: the search term (a name, a PAN or a GSTIN, posted rather
 * than put in a URL), the cursor of the page and its number. Reads only.
 */
export async function searchBusinesses(
  _state: ActionState<DirectoryPage>,
  formData: FormData,
): Promise<ActionState<DirectoryPage>> {
  const session = await requireScreenSession(screenById("owner.businesses"));
  const query = readDirectoryQuery(formData);
  if (!query.ok) return actionFailure(query.error);
  const page = await getDirectoryPage(session, {
    q: query.q,
    page: query.page,
    ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
  });
  return toActionState(page);
}

/**
 * One answer changed on the attributes page: the same parsing as onboarding, stored with
 * `PATCH /v1/businesses/{id}` on the node shown and for the year shown when the attribute is
 * stated per year. Only a role that may change the profile gets here; the answer says which
 * profile version it made, and the business's pages render again with the new value.
 */
export async function saveAttribute(_state: ActionState, formData: FormData): Promise<ActionState> {
  const input = readAnswerForm(formData);
  if (input === null) return actionFailure(t("question.error.form"));
  const screen = screenById("owner.business.attributes");
  const session = await requireScreenSession(screen, { businessId: input.businessId });
  if (!can(session, "profile.edit")) return actionFailure(t("attributes.error.role"));

  const ontology = await getOntology();
  if (!ontology.ok) return toActionState(ontology);
  const attribute = attributeOf(ontology.value, input.key);
  if (attribute === undefined) return actionFailure(t("question.error.unknown"));
  const parsed = parseAnswer(
    attribute,
    { state: input.state, values: input.values },
    { asOfFy: input.asOfFy, nodeId: input.nodeId },
  );
  if (!parsed.ok) return fieldFailure({ [ANSWER_FIELDS.value]: [parsed.error] });

  const updated = await businessGateway({ session }).update(input.businessId, {
    changes: [parsed.answer],
  });
  if (!updated.ok) return answerRefused(updated.error);
  const business = updated.value;
  const node =
    input.nodeId === business.id
      ? business
      : business.registrations.find((registration) => registration.id === input.nodeId);
  const businessId = input.businessId;
  afterMutation({
    paths: [
      hrefFor(screen, { businessId }),
      hrefFor(screenById("owner.business"), { businessId }),
      hrefFor(screenById("owner.business.snapshot"), { businessId }),
    ],
  });
  return actionSuccess(
    undefined,
    node === undefined
      ? t("attributes.saved")
      : t("attributes.savedVersion", { version: node.version }),
  );
}

/** What adding a location returned, for the form's result line. */
export interface LocationAdded {
  id: string;
  label: string;
  name: string;
  created: boolean;
  attributesHref: string;
  snapshotHref: string;
}

/**
 * Adds a location under one of the business's registrations with `POST /v1/profile/locations`
 * (the label is its natural key: an existing one is returned with created false). The
 * registration is checked against the business first, so a tampered form cannot add a location
 * under another business's registration.
 */
export async function addLocation(
  _state: ActionState<LocationAdded>,
  formData: FormData,
): Promise<ActionState<LocationAdded>> {
  const parsed = parseLocationForm(formData);
  if (!parsed.ok) {
    return parsed.fieldErrors === undefined
      ? actionFailure(parsed.formError ?? t("question.error.form"))
      : fieldFailure(parsed.fieldErrors);
  }
  const { businessId, registrationId, label, name } = parsed.value;
  const screen = screenById("owner.business.profile");
  const session = await requireScreenSession(screen, { businessId });
  if (!can(session, "profile.edit")) return actionFailure(t("attributes.error.role"));

  const gateway = businessGateway({ session });
  const business = await gateway.get(businessId);
  if (!business.ok) return toActionState(business);
  if (!business.value.registrations.some((node) => node.id === registrationId)) {
    return actionFailure(t("location.error.registration"));
  }
  const added = await gateway.addLocation({ registrationId, label, name });
  if (!added.ok) return toActionState(added);
  const location = added.value;
  const query = `?${new URLSearchParams({ node: location.id }).toString()}`;
  return actionSuccess({
    id: location.id,
    label: location.key,
    name: location.name,
    created: location.created,
    attributesHref: `${hrefFor(screenById("owner.business.attributes"), { businessId })}${query}`,
    snapshotHref: `${hrefFor(screenById("owner.business.snapshot"), { businessId })}${query}`,
  });
}
