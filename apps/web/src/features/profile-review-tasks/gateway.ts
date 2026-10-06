import "server-only";

import {
  profileNodeFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
} from "@/entities/business/mappers";
import type { ProfileNode, ReviewTask, Snapshot } from "@/entities/business/types";
import { call } from "@/server/api/client";
import { profileClient, type ClientContext, type ProfileClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { ProfileReviewPort } from "./ports";

/**
 * A tenant's profile node read for an internal user: the profile routes act for the tenant in
 * x-tenant-id, so the gateway is built with the looked-up tenant as `ClientContext.tenantId`, the
 * one way a request acts for a tenant other than the session's (data-layer.md). Tenant data is
 * never cached.
 */
export class ProfileReviewGateway implements ProfileReviewPort {
  private readonly profile: ProfileClient;

  constructor(ctx: ClientContext) {
    this.profile = profileClient(ctx);
  }

  async node(nodeId: string): Promise<Result<ProfileNode>> {
    const result = await call(
      this.profile.GET("/v1/profile/nodes/{node_id}", {
        params: { path: { node_id: nodeId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, profileNodeFromDto);
  }

  async reviewTasks(nodeId: string): Promise<Result<ReviewTask[]>> {
    const result = await call(
      this.profile.GET("/v1/profile/nodes/{node_id}/review-tasks", {
        params: { path: { node_id: nodeId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (tasks) => tasks.map(reviewTaskFromDto));
  }

  async snapshot(nodeId: string, fy: string): Promise<Result<Snapshot>> {
    const result = await call(
      this.profile.GET("/v1/profile/nodes/{node_id}/snapshot", {
        params: { path: { node_id: nodeId }, query: { fy } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, snapshotFromDto);
  }
}

/** The gateway acting for the looked-up tenant; tests add fetchImpl. */
export function profileReviewGateway(ctx: ClientContext): ProfileReviewGateway {
  return new ProfileReviewGateway(ctx);
}
