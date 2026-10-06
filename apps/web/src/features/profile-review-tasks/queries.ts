import "server-only";

import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { readOntology } from "@/server/ontology";
import { ok, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { profileReviewGateway } from "./gateway";
import { nodeReviewView, type NodeReviewView } from "./model/node-review";

/**
 * The lookup's read: the node of the named tenant first (an id that tenant does not hold is
 * null, the page's "no such node" answer), then its open review tasks, its snapshot for the year
 * and the ontology in parallel. The ontology only words the page, so its failure leaves the
 * values as stored; any other failure is the page's error.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export async function getNodeReview(
  session: ClientPrincipal,
  lookup: { tenantId: string; nodeId: string; fy: string },
  deps: QueryDeps = {},
): Promise<Result<NodeReviewView | null>> {
  const gateway = profileReviewGateway({
    session,
    tenantId: lookup.tenantId,
    fetchImpl: deps.fetchImpl,
  });
  const node = await gateway.node(lookup.nodeId);
  if (!node.ok) return node.error.kind === "not_found" ? ok(null) : node;
  const [tasks, snapshot, ontology] = await Promise.all([
    gateway.reviewTasks(lookup.nodeId),
    gateway.snapshot(lookup.nodeId, lookup.fy),
    readOntology({ fetchImpl: deps.fetchImpl }),
  ]);
  if (!tasks.ok) return tasks;
  if (!snapshot.ok) return snapshot;
  return ok(
    nodeReviewView({
      pathname: hrefFor(screenById("admin.profiles.review-tasks")),
      tenantId: lookup.tenantId,
      fy: lookup.fy,
      node: node.value,
      tasks: tasks.value,
      snapshot: snapshot.value,
      ontology: ontology.ok ? ontology.value : null,
    }),
  );
}
