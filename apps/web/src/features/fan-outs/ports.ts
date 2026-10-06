import type { FanOutHold, FanOutRun, FanOutRunPage } from "@/entities/applicability/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/**
 * What the fan-out screens need from the applicability engine: the runs, newest first, a page at
 * a time; one version's run; the global hold; and the admin's controls (pause, resume, cancel,
 * set and release the hold), each with the reason the engine keeps in its audit log. None of it
 * names a tenant: a fan-out runs over every tenant.
 */
export interface FanOutPort {
  list(query: { limit: number; cursor?: string }): Promise<Result<FanOutRunPage>>;
  get(ruleVersionId: string): Promise<Result<FanOutRun>>;
  hold(): Promise<Result<FanOutHold>>;
  setHold(held: boolean, reason: string): Promise<Result<FanOutHold>>;
  pause(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>>;
  resume(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>>;
  cancel(ruleVersionId: string, reason: string): Promise<Result<FanOutRun>>;
}

/** And the rule version a run decides, from the rulebook, to name it and to know its status. */
export interface FanOutVersionsPort {
  version(ruleVersionId: string): Promise<Result<RuleVersion>>;
}
