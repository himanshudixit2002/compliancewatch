import type { DryRunReport, DryRunRequest } from "@/entities/applicability/types";
import type { Result } from "@/server/result";

/**
 * What the impact explorer needs from the applicability engine: a dry run of a rule version in any
 * status, or of a specification no version holds yet, over the business directory of one tenant or
 * every tenant. It stores no decision and sends nothing; the engine writes one audit entry.
 */
export interface DryRunPort {
  dryRun(request: DryRunRequest): Promise<Result<DryRunReport>>;
}
