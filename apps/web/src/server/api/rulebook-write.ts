import "server-only";

import type { rulebook } from "@compliancewatch/contracts/openapi";
import type { Client } from "openapi-fetch";
import {
  approvalToDto,
  approvedFromDto,
  entityDecidedFromDto,
  entityDecisionToDto,
  rejectionToDto,
  relationCandidateFromDto,
} from "@/entities/rulebook/mappers";
import type {
  CandidateApproval,
  CandidateApproved,
  CandidateRejection,
  EntityGroupDecided,
  EntityGroupDecision,
  RelationCandidate,
} from "@/entities/rulebook/types";
import { isProblemOf } from "@/entities/problem/mappers";
import type { FlagName } from "@/shared/config/flags";
import { isRegulatory } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import { getEnv, serviceUrl } from "../env";
import { isEnabled } from "../flags";
import { err, mapBody, ok, webError, type ApiError, type Result } from "../result";
import { WRITE_TOKEN_HEADER, call, createServiceClient } from "./client";
import type { ClientContext } from "./services";

/**
 * The rulebook's two shared secrets (ADR-018) and the only module that sends them. The write
 * token (CW_WEB_RULEBOOK_WRITE_TOKEN, the rulebook's CW_RULEBOOK_WRITE_TOKEN) opens the pipeline's
 * writes: documents, mentions, relation staging. The review token (CW_WEB_RULEBOOK_REVIEW_TOKEN,
 * the rulebook's CW_RULEBOOK_REVIEW_TOKEN) opens the analyst's decisions: entity groups and
 * relation candidates. The write token does not open a decision, and neither token is ever sent
 * on another call, logged, put in an error or returned.
 *
 *   rulebookWriteClient(ctx)    x-cw-write-token, after a regulatory-role check
 *   rulebookReviewClient(ctx)   x-cw-review-token, after a regulatory-role check
 *   rulebookWrites(ctx)         the decisions an admin tool makes, behind the role, the flag
 *                               web.admin_rulebook_writes and the review token; a refusal is a
 *                               port whose every method answers the refusal without a request
 *   rulebookWriteAccess(ctx)    whether a form may offer those decisions, and why not
 *
 * The body's decided_by is the session's user id, filled here, so a form cannot name someone
 * else; the rulebook takes it as the caller's word until identity issues verified claims. A
 * rulebook answer about a token (wrong: 401; not configured on the rulebook: 503) is reworded to
 * say which side to fix, with the variable to set and never its value.
 */
export const REVIEW_TOKEN_HEADER = "x-cw-review-token";

/** The flag that gates every decision an admin tool sends to the rulebook. */
export const RULEBOOK_WRITES_FLAG: FlagName = "web.admin_rulebook_writes";

export type RulebookClient = Client<rulebook.paths>;

/** The rulebook's problem slugs about its tokens, and the message each one gets here. */
const TOKEN_PROBLEMS = {
  "rulebook-review-token-invalid": {
    title: () => t("rulebookWrites.reviewTokenInvalid"),
    detail: () => t("rulebookWrites.reviewTokenInvalidDetail"),
  },
  "rulebook-reviews-disabled": {
    title: () => t("rulebookWrites.reviewsDisabled"),
    detail: () => t("rulebookWrites.reviewsDisabledDetail"),
  },
  "rulebook-write-token-invalid": {
    title: () => t("rulebookWrites.writeTokenInvalid"),
    detail: () => t("rulebookWrites.writeTokenInvalidDetail"),
  },
  "rulebook-writes-disabled": {
    title: () => t("rulebookWrites.writesDisabled"),
    detail: () => t("rulebookWrites.writesDisabledDetail"),
  },
} as const;

/**
 * A rulebook refusal about a token, reworded to say which side to fix: the web app's variable
 * when the token is wrong, the rulebook's when it has none. Any other error passes unchanged.
 */
export function explainTokenProblem(error: ApiError): ApiError {
  for (const [slug, wording] of Object.entries(TOKEN_PROBLEMS)) {
    if (error.problem !== undefined && isProblemOf(error.problem, slug)) {
      const title = wording.title();
      return {
        ...error,
        message: title,
        problem: { ...error.problem, title, detail: wording.detail() },
      };
    }
  }
  return error;
}

function roleRefusal(): ApiError {
  return webError(
    "forbidden",
    "web-regulatory-role-required",
    t("rulebookWrites.roleRequired"),
    t("rulebookWrites.roleRequiredDetail"),
  );
}

function tokenClient(
  ctx: ClientContext,
  header: string,
  token: string | undefined,
  missing: () => ApiError,
): Result<RulebookClient> {
  if (!isRegulatory(ctx.session)) return err(roleRefusal());
  if (token === undefined) return err(missing());
  const env = getEnv();
  return ok(
    createServiceClient<rulebook.paths>({
      service: "rulebook",
      baseUrl: serviceUrl("rulebook", env),
      timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
      fetchImpl: ctx.fetchImpl,
      // No tenant header: the rulebook's records belong to no tenant.
      headers: { [header]: token },
    }),
  );
}

/** The rulebook client for the pipeline's writes, with the write token. */
export function rulebookWriteClient(ctx: ClientContext): Result<RulebookClient> {
  return tokenClient(ctx, WRITE_TOKEN_HEADER, getEnv().CW_WEB_RULEBOOK_WRITE_TOKEN, () =>
    webError(
      "unavailable",
      "web-write-token-missing",
      t("rulebookWrites.writeTokenMissing"),
      t("rulebookWrites.writeTokenMissingDetail"),
    ),
  );
}

/** The rulebook client for the analyst's decisions, with the review token. */
export function rulebookReviewClient(ctx: ClientContext): Result<RulebookClient> {
  return tokenClient(ctx, REVIEW_TOKEN_HEADER, getEnv().CW_WEB_RULEBOOK_REVIEW_TOKEN, () =>
    webError(
      "unavailable",
      "web-review-token-missing",
      t("rulebookWrites.reviewTokenMissing"),
      t("rulebookWrites.reviewTokenMissingDetail"),
    ),
  );
}

/** The decisions the admin tools send to the rulebook. */
export interface RulebookWritePort {
  decideEntityGroup(decision: EntityGroupDecision): Promise<Result<EntityGroupDecided>>;
  approveCandidate(
    candidateId: string,
    approval: CandidateApproval,
  ): Promise<Result<CandidateApproved>>;
  rejectCandidate(
    candidateId: string,
    rejection: CandidateRejection,
  ): Promise<Result<RelationCandidate>>;
}

function explained<T>(result: Result<T>): Result<T> {
  return result.ok ? result : err(explainTokenProblem(result.error));
}

/** The decisions over the review client, with decided_by from the session. */
export class RulebookWriteGateway implements RulebookWritePort {
  private readonly client: RulebookClient;
  private readonly decidedBy: string;

  constructor(client: RulebookClient, decidedBy: string) {
    this.client = client;
    this.decidedBy = decidedBy;
  }

  async decideEntityGroup(decision: EntityGroupDecision): Promise<Result<EntityGroupDecided>> {
    const result = await call(
      this.client.POST("/v1/rulebook/review/entities/decisions", {
        body: entityDecisionToDto(decision, this.decidedBy),
      }),
    );
    return explained(mapBody(result, entityDecidedFromDto));
  }

  async approveCandidate(
    candidateId: string,
    approval: CandidateApproval,
  ): Promise<Result<CandidateApproved>> {
    const result = await call(
      this.client.POST("/v1/rulebook/review/relations/{candidate_id}/approve", {
        params: { path: { candidate_id: candidateId } },
        body: approvalToDto(approval, this.decidedBy),
      }),
    );
    return explained(mapBody(result, approvedFromDto));
  }

  async rejectCandidate(
    candidateId: string,
    rejection: CandidateRejection,
  ): Promise<Result<RelationCandidate>> {
    const result = await call(
      this.client.POST("/v1/rulebook/review/relations/{candidate_id}/reject", {
        params: { path: { candidate_id: candidateId } },
        body: rejectionToDto(rejection, this.decidedBy),
      }),
    );
    return explained(mapBody(result, relationCandidateFromDto));
  }
}

/** A port that refuses every decision with the same error and sends nothing. */
export class RefusedWriteGateway implements RulebookWritePort {
  readonly error: ApiError;

  constructor(error: ApiError) {
    this.error = error;
  }

  async decideEntityGroup(): Promise<Result<EntityGroupDecided>> {
    return err(this.error);
  }

  async approveCandidate(): Promise<Result<CandidateApproved>> {
    return err(this.error);
  }

  async rejectCandidate(): Promise<Result<RelationCandidate>> {
    return err(this.error);
  }
}

/** Why the admin tools may not send decisions. */
export type WriteRefusal = "role" | "flag" | "token";

export type WriteAccess =
  { allowed: true } | { allowed: false; refusal: WriteRefusal; error: ApiError; flag: FlagName };

type Checked =
  | { allowed: true; client: RulebookClient; decidedBy: string }
  | { allowed: false; refusal: WriteRefusal; error: ApiError };

function flagRefusal(): ApiError {
  return webError(
    "unavailable",
    "web-rulebook-writes-off",
    t("rulebookWrites.flagOff", { flag: RULEBOOK_WRITES_FLAG }),
    t("rulebookWrites.flagOffDetail", { flag: RULEBOOK_WRITES_FLAG }),
  );
}

/** The role, then the flag for the session's tenant, then the review token. */
async function check(ctx: ClientContext): Promise<Checked> {
  const { session } = ctx;
  if (session === null || !isRegulatory(session)) {
    return { allowed: false, refusal: "role", error: roleRefusal() };
  }
  if (!(await isEnabled(RULEBOOK_WRITES_FLAG, { tenantId: session.tenantId }))) {
    return { allowed: false, refusal: "flag", error: flagRefusal() };
  }
  const client = rulebookReviewClient(ctx);
  if (!client.ok) return { allowed: false, refusal: "token", error: client.error };
  return { allowed: true, client: client.value, decidedBy: session.userId };
}

/**
 * Whether the session may send decisions to the rulebook: a regulatory role, the flag on for the
 * session's tenant, and the review token configured. A form renders disabled with the refusal's
 * message, which names the flag or the variable to set.
 */
export async function rulebookWriteAccess(ctx: ClientContext): Promise<WriteAccess> {
  const checked = await check(ctx);
  if (checked.allowed) return { allowed: true };
  return {
    allowed: false,
    refusal: checked.refusal,
    error: checked.error,
    flag: RULEBOOK_WRITES_FLAG,
  };
}

/**
 * The decisions port for an admin action: the gateway over the review client when the role, the
 * flag and the token allow it, else a port that answers the refusal to every call. The action
 * calls this itself, so a request made without the form (a replayed POST) meets the same checks.
 */
export async function rulebookWrites(ctx: ClientContext): Promise<RulebookWritePort> {
  const checked = await check(ctx);
  return checked.allowed
    ? new RulebookWriteGateway(checked.client, checked.decidedBy)
    : new RefusedWriteGateway(checked.error);
}
