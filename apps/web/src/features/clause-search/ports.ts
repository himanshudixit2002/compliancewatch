import type { SearchHit, SearchQuery } from "@/entities/rulebook/types";
import type { Result } from "@/server/result";

/** The rulebook's hybrid clause search. */
export interface SearchPort {
  search(query: SearchQuery): Promise<Result<readonly SearchHit[]>>;
}
