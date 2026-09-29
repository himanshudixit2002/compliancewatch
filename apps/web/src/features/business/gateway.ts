import "server-only";

import {
  businessChangesToDto,
  businessCreatedFromDto,
  businessFromDto,
  businessPageFromDto,
  newBusinessToDto,
  newLocationToDto,
  newRegistrationToDto,
  onboardingFromDto,
  profileNodeFromDto,
  registrationAddedFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
} from "@/entities/business/mappers";
import type {
  Business,
  BusinessChanges,
  BusinessCreated,
  BusinessListQuery,
  BusinessPage,
  NewBusiness,
  NewLocation,
  NewRegistration,
  Onboarding,
  ProfileNode,
  RegistrationAdded,
  ReviewTask,
  Snapshot,
} from "@/entities/business/types";
import { call } from "@/server/api/client";
import { profileClient, type ClientContext, type ProfileClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { BusinessPort, ProfileNodePort, RequestHeaders } from "./ports";

/**
 * The business and profile node calls over the typed profile client. Every call carries the
 * session's tenant as x-tenant-id (the client factory adds it) and a fresh x-request-id, and is
 * never cached: a business is tenant data and must be current. The two creating calls pass on
 * the Idempotency-Key header the action built from the form; without one the service answers
 * 428 (`precondition_required`), which is the web layer's own mistake and reads as such.
 */
export class BusinessGateway implements BusinessPort, ProfileNodePort {
  private readonly client: ProfileClient;

  constructor(ctx: ClientContext) {
    this.client = profileClient(ctx);
  }

  async list(query: BusinessListQuery = {}): Promise<Result<BusinessPage>> {
    const params: { q?: string; limit?: number; cursor?: string } = {};
    if (query.q !== undefined && query.q.trim() !== "") params.q = query.q.trim();
    if (query.limit !== undefined) params.limit = query.limit;
    if (query.cursor !== undefined && query.cursor !== "") params.cursor = query.cursor;
    const result = await call(
      this.client.GET("/v1/businesses", { params: { query: params }, ...uncachedRead() }),
    );
    return mapBody(result, businessPageFromDto);
  }

  async create(input: NewBusiness, idempotency: RequestHeaders): Promise<Result<BusinessCreated>> {
    const result = await call(
      this.client.POST("/v1/businesses", {
        body: newBusinessToDto(input),
        // The spec marks the header required; the value comes from the form's hidden input.
        params: { header: idempotency as { "Idempotency-Key": string } },
      }),
    );
    return mapBody(result, businessCreatedFromDto);
  }

  async get(businessId: string): Promise<Result<Business>> {
    const result = await call(
      this.client.GET("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, businessFromDto);
  }

  async update(businessId: string, changes: BusinessChanges): Promise<Result<Business>> {
    const result = await call(
      this.client.PATCH("/v1/businesses/{business_id}", {
        params: { path: { business_id: businessId } },
        body: businessChangesToDto(changes),
      }),
    );
    return mapBody(result, businessFromDto);
  }

  async onboarding(businessId: string): Promise<Result<Onboarding>> {
    const result = await call(
      this.client.GET("/v1/businesses/{business_id}/onboarding", {
        params: { path: { business_id: businessId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, onboardingFromDto);
  }

  async addRegistration(
    businessId: string,
    input: NewRegistration,
    idempotency: RequestHeaders,
  ): Promise<Result<RegistrationAdded>> {
    const result = await call(
      this.client.POST("/v1/businesses/{business_id}/registrations", {
        params: {
          path: { business_id: businessId },
          header: idempotency as { "Idempotency-Key": string },
        },
        body: newRegistrationToDto(input),
      }),
    );
    return mapBody(result, registrationAddedFromDto);
  }

  async node(nodeId: string): Promise<Result<ProfileNode>> {
    const result = await call(
      this.client.GET("/v1/profile/nodes/{node_id}", {
        params: { path: { node_id: nodeId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, profileNodeFromDto);
  }

  async addLocation(input: NewLocation): Promise<Result<ProfileNode>> {
    const result = await call(
      this.client.POST("/v1/profile/locations", { body: newLocationToDto(input) }),
    );
    return mapBody(result, profileNodeFromDto);
  }

  async snapshot(nodeId: string, fy?: string): Promise<Result<Snapshot>> {
    const result = await call(
      this.client.GET("/v1/profile/nodes/{node_id}/snapshot", {
        params: { path: { node_id: nodeId }, query: fy === undefined ? {} : { fy } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, snapshotFromDto);
  }

  async reviewTasks(nodeId: string): Promise<Result<ReviewTask[]>> {
    const result = await call(
      this.client.GET("/v1/profile/nodes/{node_id}/review-tasks", {
        params: { path: { node_id: nodeId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (tasks) => tasks.map(reviewTaskFromDto));
  }
}

/** The gateway for a page or an action: `businessGateway({ session })`; tests add fetchImpl. */
export function businessGateway(ctx: ClientContext): BusinessGateway {
  return new BusinessGateway(ctx);
}
