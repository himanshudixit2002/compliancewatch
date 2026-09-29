import { expectOk, type SeedClients } from "../http.mts";
import { DEMO, attributeChanges, seedFinancialYear } from "../lib.mts";

/**
 * The demo business on the profile service: the registration (found or created by its GSTIN,
 * with its entity by the PAN), the pre-fill from the static GSTIN lookup, the owner's answers
 * on both nodes, then the next open question, the snapshot and the review tasks the answers
 * opened, read back for the summary.
 */
export interface ProfileResult {
  entityNodeId: string;
  registrationNodeId: string;
  created: boolean;
  prefilled: string[];
  answered: number;
  nextQuestion: string | null;
  snapshotAttributes: number;
  openReviewTasks: number;
}

export async function seedProfile(
  clients: SeedClients,
  ownerId: string,
  log: (line: string) => void,
): Promise<ProfileResult> {
  const step = "profile";
  const fy = seedFinancialYear();
  const registered = await expectOk(
    step,
    "POST /v1/profile/registrations",
    clients.profile.POST("/v1/profile/registrations", {
      body: { gstin: DEMO.gstin, name: DEMO.registrationName, entity_name: DEMO.entityName },
    }),
  );
  const registrationNodeId = registered.data.id;
  const entityNodeId = registered.data.parent_id;
  if (entityNodeId === null || entityNodeId === undefined) {
    throw new Error(`profile: registration ${registrationNodeId} has no parent entity node`);
  }
  const prefill = await expectOk(
    step,
    "POST /v1/profile/registrations/{node_id}/prefill",
    clients.profile.POST("/v1/profile/registrations/{node_id}/prefill", {
      params: { path: { node_id: registrationNodeId } },
      body: { changed_by: ownerId },
    }),
  );
  const changes = attributeChanges(fy);
  let answered = 0;
  for (const [nodeId, list] of [
    [entityNodeId, changes.entity],
    [registrationNodeId, changes.registration],
  ] as const) {
    await expectOk(
      step,
      `PUT /v1/profile/nodes/{node_id}/attributes (${list.length} changes)`,
      clients.profile.PUT("/v1/profile/nodes/{node_id}/attributes", {
        params: { path: { node_id: nodeId } },
        body: { changes: list, source: "user_input", changed_by: ownerId },
      }),
    );
    answered += list.length;
  }
  const next = await expectOk(
    step,
    "GET /v1/profile/nodes/{node_id}/next-question",
    clients.profile.GET("/v1/profile/nodes/{node_id}/next-question", {
      params: { path: { node_id: registrationNodeId }, query: { fy } },
    }),
  );
  const snapshot = await expectOk(
    step,
    "GET /v1/profile/nodes/{node_id}/snapshot",
    clients.profile.GET("/v1/profile/nodes/{node_id}/snapshot", {
      params: { path: { node_id: registrationNodeId }, query: { fy } },
    }),
  );
  const tasks = await expectOk(
    step,
    "GET /v1/profile/nodes/{node_id}/review-tasks",
    clients.profile.GET("/v1/profile/nodes/{node_id}/review-tasks", {
      params: { path: { node_id: registrationNodeId } },
    }),
  );
  const result: ProfileResult = {
    entityNodeId,
    registrationNodeId,
    created: registered.data.created ?? false,
    prefilled: [...prefill.data.applied],
    answered,
    nextQuestion: next.data.attribute,
    snapshotAttributes: Object.keys(snapshot.data.attributes).length,
    openReviewTasks: tasks.data.filter((task) => task.open).length,
  };
  log(
    `profile: registration ${registrationNodeId} (${result.created ? "created" : "already there"}),` +
      ` entity ${entityNodeId}; pre-filled ${result.prefilled.length}, answered ${answered},` +
      ` snapshot ${fy} holds ${result.snapshotAttributes} attributes,` +
      ` next question ${result.nextQuestion ?? "none"}, open review tasks ${result.openReviewTasks}`,
  );
  return result;
}
