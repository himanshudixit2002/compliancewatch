import type { Result } from "@/server/result";

/** How many records a list held, read from one page of up to `COUNT_PAGE` rows. */
export interface ListCount {
  count: number;
  /** The page was full, so there may be more than `count`. */
  capped: boolean;
  /** The records behind the rows, where a row groups several (open mentions per group). */
  within?: number;
}

/** What the admin home counts: the two review queues and the two registries it can read. */
export interface AdminCountsPort {
  entityGroups(): Promise<Result<ListCount>>;
  openRelationCandidates(): Promise<Result<ListCount>>;
  rules(): Promise<Result<ListCount>>;
  prompts(): Promise<Result<ListCount>>;
}
