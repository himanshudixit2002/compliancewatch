import type { ProfileNode, ReviewTask, Snapshot } from "@/entities/business/types";
import type { Result } from "@/server/result";

/** One node of the looked-up tenant, read with its tenant as x-tenant-id. */
export interface ProfileReviewPort {
  node(nodeId: string): Promise<Result<ProfileNode>>;
  /** The node's open review tasks. */
  reviewTasks(nodeId: string): Promise<Result<ReviewTask[]>>;
  /** What the engine evaluates for the node in a financial year ("2026-27"). */
  snapshot(nodeId: string, fy: string): Promise<Result<Snapshot>>;
}
