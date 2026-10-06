import type { Applicability, ChangeImpact } from "@/entities/applicability/types";
import type { Business } from "@/entities/business/types";
import type { BulkNotificationResult } from "@/entities/notification/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { Replayable } from "@/server/api/idempotency";
import type { Result } from "@/server/result";

/** The headers a write carries: the form's Idempotency-Key, or nothing. */
export type WriteHeaders = Readonly<Record<string, string>>;

/**
 * What a CA firm's affected clients screen needs: the change's impact for the firm (its clients,
 * each with its businesses' latest decision of the version, a page of clients at a time, filtered
 * by result), the change itself from the rulebook, each client's name from the profile service,
 * and the bulk change card to the affected clients' own people, with the form's Idempotency-Key.
 */
export interface ChangeImpactPort {
  impact(
    ruleVersionId: string,
    query: { result?: Applicability; limit: number; cursor?: string },
  ): Promise<Result<ChangeImpact>>;
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
  business(businessId: string): Promise<Result<Business>>;
  sendChangeCards(
    ruleVersionId: string,
    businessIds: readonly string[],
    headers: WriteHeaders,
  ): Promise<Result<Replayable<BulkNotificationResult>>>;
}
