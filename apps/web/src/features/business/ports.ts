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
import type { Result } from "@/server/result";

/**
 * What the owner and CA-firm screens need from the profile service, in two ports.
 *
 * `BusinessPort` is the business API (tagged public in the profile spec): the tenant's list,
 * creating a business from a GSTIN or a PAN, reading and changing one, the onboarding
 * checklist, and adding a registration. The two creating calls carry the Idempotency-Key the
 * form minted (`idempotencyHeaders(formData, "profile.create-business")`), so a double submit
 * records one business.
 *
 * `ProfileNodePort` is the part of the profile node routes the business API does not cover:
 * one node (a location, or a parent in a lineage), adding a location under a registration, the
 * snapshot per financial year, and the review tasks a node's answers opened.
 */
export type RequestHeaders = Readonly<Record<string, string>>;

export interface BusinessPort {
  list(query?: BusinessListQuery): Promise<Result<BusinessPage>>;
  create(input: NewBusiness, idempotency: RequestHeaders): Promise<Result<BusinessCreated>>;
  get(businessId: string): Promise<Result<Business>>;
  update(businessId: string, changes: BusinessChanges): Promise<Result<Business>>;
  onboarding(businessId: string): Promise<Result<Onboarding>>;
  addRegistration(
    businessId: string,
    input: NewRegistration,
    idempotency: RequestHeaders,
  ): Promise<Result<RegistrationAdded>>;
}

export interface ProfileNodePort {
  node(nodeId: string): Promise<Result<ProfileNode>>;
  addLocation(input: NewLocation): Promise<Result<ProfileNode>>;
  /** The node's values with inheritance applied; per-year values for `fy`, none without it. */
  snapshot(nodeId: string, fy?: string): Promise<Result<Snapshot>>;
  reviewTasks(nodeId: string): Promise<Result<ReviewTask[]>>;
}
