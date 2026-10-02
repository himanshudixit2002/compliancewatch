import "server-only";

import type { rulebook } from "@compliancewatch/contracts/openapi";
import type { Client } from "openapi-fetch";
import { isRegulatory } from "@/shared/config/roles";
import { getEnv, serviceUrl } from "../env";
import { createServiceClient } from "./client";
import { type Result, webError } from "../result";
import type { ClientContext } from "./services";

type ReadClient = Client<rulebook.paths>;

export interface RulebookReviewReadPort {
  listEntityGroups(params: { session: ClientContext["session"]; pending?: boolean }): Promise<Result<rulebook.components["schemas"]["MentionGroupOut"][]>>;
  listRelationCandidates(params: { session: ClientContext["session"]; pending?: boolean }): Promise<Result<rulebook.components["schemas"]["RelationCandidateOut"][]>>;
}

function accessError(): Result<never> {
  return { ok: false as const, error: webError("forbidden", "web-regulatory-role-required", "A regulatory role is required", "Only reviewers and admins can read the review queue.") };
}

function tokenError(): Result<never> {
  return { ok: false as const, error: webError("unavailable", "web-review-token-missing", "The review token is not configured", "Set CW_WEB_RULEBOOK_REVIEW_TOKEN.") };
}

function fetchError(status: number, message?: string): Result<never> {
  return { ok: false as const, error: webError("server", "web-review-fetch-failed", `Service returned ${status}`, message) };
}

function buildClient(): ReadClient {
  const env = getEnv();
  const token = env.CW_WEB_RULEBOOK_REVIEW_TOKEN;
  return createServiceClient<rulebook.paths>({
    service: "rulebook",
    baseUrl: serviceUrl("rulebook", env),
    timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
    headers: token !== undefined ? { "x-cw-review-token": token } : {},
  });
}

export function rulebookReviewReads(): RulebookReviewReadPort {
  return {
    async listEntityGroups({ session }) {
      if (!isRegulatory(session)) return accessError();
      const token = getEnv().CW_WEB_RULEBOOK_REVIEW_TOKEN;
      if (!token) return tokenError();
      const client = buildClient();
      const result = await client.GET("/v1/rulebook/review/entities");
      if (!result.response.ok) {
        return fetchError(result.response.status);
      }
      return { ok: true as const, value: (result.data ?? []) };
    },
    async listRelationCandidates({ session }) {
      if (!isRegulatory(session)) return accessError();
      const token = getEnv().CW_WEB_RULEBOOK_REVIEW_TOKEN;
      if (!token) return tokenError();
      const client = buildClient();
      const result = await client.GET("/v1/rulebook/review/relations");
      if (!result.response.ok) {
        return fetchError(result.response.status);
      }
      return { ok: true as const, value: (result.data ?? []) };
    },
  };
}