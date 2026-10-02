import "server-only";

import type { Business, ProfileNode, ReviewTask } from "@/entities/business/types";
import type { ClientContext } from "@/server/api/services";
import { readOntology } from "@/server/ontology";
import { err, mapResult, ok, webError, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { businessGateway, type BusinessGateway } from "./gateway";
import {
  attributesView,
  businessHeader,
  businessHomeView,
  resolveNode,
  reviewTasksView,
  selectedFinancialYear,
  snapshotView,
  type AttributesView,
  type BusinessHeader,
  type BusinessHomeView,
  type ResolvedNode,
  type ReviewTasksView,
  type SnapshotView,
} from "./model/business-pages";
import { DIRECTORY_PAGE_SIZE, directoryPage, type DirectoryPage } from "./model/directory";
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

/** Every review task on the business's entity and registrations, in that order. */
async function tasksOf(
  gateway: BusinessGateway,
  business: Business,
): Promise<Result<ReviewTask[]>> {
  const nodeIds = [business.id, ...business.registrations.map((node) => node.id)];
  const lists = await Promise.all(nodeIds.map((id) => gateway.reviewTasks(id)));
  const tasks: ReviewTask[] = [];
  for (const list of lists) {
    if (!list.ok) return err(list.error);
    tasks.push(...list.value);
  }
  return ok(tasks);
}

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
  const tasks = await tasksOf(gateway, business.value);
  if (!tasks.ok) return tasks;
  return ok({
    business: business.value,
    onboarding: onboarding.value,
    ontology: ontology.value,
    tasks: tasks.value,
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

/** A page of the tenant's businesses, by name; `q` matches a name, a PAN or a GSTIN. */
export async function getDirectoryPage(
  session: QuerySession,
  query: { q: string; cursor?: string; page: number },
  deps: BusinessQueryDeps = {},
): Promise<Result<DirectoryPage>> {
  const page = await businessGateway({ session, fetchImpl: deps.fetchImpl }).list({
    q: query.q,
    limit: DIRECTORY_PAGE_SIZE,
    ...(query.cursor === undefined ? {} : { cursor: query.cursor }),
  });
  const home = screenById("owner.business");
  return mapResult(page, (value) =>
    directoryPage(value, query.q, query.page, (businessId) => hrefFor(home, { businessId })),
  );
}

export async function getBusinessHome(
  session: QuerySession,
  businessId: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<BusinessHomeView>> {
  const gateway = businessGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, onboarding] = await Promise.all([
    gateway.get(businessId),
    gateway.onboarding(businessId),
  ]);
  if (!business.ok) return business;
  if (!onboarding.ok) return onboarding;
  const tasks = await tasksOf(gateway, business.value);
  return mapResult(tasks, (value) => businessHomeView(business.value, onboarding.value, value));
}

export async function getProfilePage(
  session: QuerySession,
  businessId: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<BusinessHeader>> {
  const business = await businessGateway({ session, fetchImpl: deps.fetchImpl }).get(businessId);
  return mapResult(business, businessHeader);
}

const NOT_IN_BUSINESS = () =>
  webError(
    "not_found",
    "web-node-not-in-business",
    "This node is not part of the business",
    "The node is the business, one of its registrations, or a location under one of them.",
  );

/** The business and the node a page is about (the business itself without a node id). */
async function businessAndNode(
  gateway: BusinessGateway,
  businessId: string,
  nodeId: string | undefined,
): Promise<Result<{ business: Business; resolved: ResolvedNode }>> {
  const business = await gateway.get(businessId);
  if (!business.ok) return business;
  const known =
    nodeId === undefined ||
    nodeId === business.value.id ||
    business.value.registrations.some((node) => node.id === nodeId);
  let location: ProfileNode | undefined;
  if (!known && nodeId !== undefined) {
    const node = await gateway.node(nodeId);
    if (!node.ok) return node.error.kind === "not_found" ? err(NOT_IN_BUSINESS()) : node;
    location = node.value;
  }
  const resolved = resolveNode(business.value, nodeId, location);
  return resolved === null ? err(NOT_IN_BUSINESS()) : ok({ business: business.value, resolved });
}

export interface NodePageQuery {
  node?: string;
  fy?: string;
}

export async function getAttributesPage(
  session: QuerySession,
  businessId: string,
  query: NodePageQuery & { edit?: string; canEdit: boolean },
  deps: BusinessQueryDeps & { now?: Date } = {},
): Promise<Result<AttributesView>> {
  const gateway = businessGateway({ session, fetchImpl: deps.fetchImpl });
  const [found, ontology] = await Promise.all([
    businessAndNode(gateway, businessId, query.node),
    readOntology({ fetchImpl: deps.fetchImpl }),
  ]);
  if (!found.ok) return found;
  if (!ontology.ok) return ontology;
  const fy = selectedFinancialYear(query.fy, deps.now);
  const screen = screenById("owner.business.attributes");
  const nodeId = found.value.resolved.node.id;
  return ok(
    attributesView({
      business: found.value.business,
      resolved: found.value.resolved,
      ontology: ontology.value,
      fy,
      ...(query.edit === undefined ? {} : { edit: query.edit }),
      canEdit: query.canEdit,
      editHref: (key) =>
        `${hrefFor(screen, { businessId })}?${new URLSearchParams({ node: nodeId, fy, edit: key }).toString()}`,
      ...(deps.now === undefined ? {} : { now: deps.now }),
    }),
  );
}

export async function getSnapshotPage(
  session: QuerySession,
  businessId: string,
  query: NodePageQuery,
  deps: BusinessQueryDeps & { now?: Date } = {},
): Promise<Result<SnapshotView>> {
  const gateway = businessGateway({ session, fetchImpl: deps.fetchImpl });
  const [found, ontology] = await Promise.all([
    businessAndNode(gateway, businessId, query.node),
    readOntology({ fetchImpl: deps.fetchImpl }),
  ]);
  if (!found.ok) return found;
  if (!ontology.ok) return ontology;
  const fy = selectedFinancialYear(query.fy, deps.now);
  const snapshot = await gateway.snapshot(found.value.resolved.node.id, fy);
  if (!snapshot.ok) return snapshot;
  return ok(
    snapshotView(
      found.value.business,
      found.value.resolved,
      snapshot.value,
      ontology.value,
      fy,
      deps.now,
    ),
  );
}

export async function getReviewTasksPage(
  session: QuerySession,
  businessId: string,
  deps: BusinessQueryDeps = {},
): Promise<Result<ReviewTasksView>> {
  const gateway = businessGateway({ session, fetchImpl: deps.fetchImpl });
  const business = await gateway.get(businessId);
  if (!business.ok) return business;
  const tasks = await tasksOf(gateway, business.value);
  return mapResult(tasks, (value) => reviewTasksView(business.value, value));
}
