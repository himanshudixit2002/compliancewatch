import "server-only";

import type { ReviewTask } from "@/entities/business/types";
import type { ClientContext } from "@/server/api/services";
import { readOntology } from "@/server/ontology";
import { err, mapResult, ok, type Result } from "@/server/result";
import { businessGateway } from "./gateway";
import {
  doneSummaryView,
  questionStepView,
  type DoneSummaryView,
  type OnboardingState,
  type QuestionStepView,
} from "./model/onboarding-step";

/**
 * The owner and CA screens' reads, composed from the business gateway and the ontology into the
 * views the pages render. Every read is tenant-scoped through the session and uncached; the
 * ontology is the shared cached read. A failure anywhere returns that call's error, so a page
 * shows one problem with its correlation id rather than half a view.
 */
export interface BusinessQueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

/** The business, its checklist, the ontology and every review task on its nodes. */
export async function loadOnboardingState(
  session: QuerySession,
  businessId: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<OnboardingState>> {
  const gateway = businessGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, onboarding, ontology] = await Promise.all([
    gateway.get(businessId),
    gateway.onboarding(businessId),
    readOntology({ fetchImpl: deps.fetchImpl }),
  ]);
  if (!business.ok) return business;
  if (!onboarding.ok) return onboarding;
  if (!ontology.ok) return ontology;
  const nodeIds = [business.value.id, ...business.value.registrations.map((node) => node.id)];
  const lists = await Promise.all(nodeIds.map((id) => gateway.reviewTasks(id)));
  const tasks: ReviewTask[] = [];
  for (const list of lists) {
    if (!list.ok) return err(list.error);
    tasks.push(...list.value);
  }
  return ok({
    business: business.value,
    onboarding: onboarding.value,
    ontology: ontology.value,
    tasks,
  });
}

export async function getQuestionStep(
  session: QuerySession,
  businessId: string,
  skipped: ReadonlySet<string>,
  saved?: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<QuestionStepView>> {
  const state = await loadOnboardingState(session, businessId, deps);
  return mapResult(state, (value) => questionStepView(value, skipped, saved));
}

export async function getDoneSummary(
  session: QuerySession,
  businessId: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<DoneSummaryView>> {
  const state = await loadOnboardingState(session, businessId, deps);
  return mapResult(state, doneSummaryView);
}
