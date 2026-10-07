import type { DocumentDetail } from "@/entities/pipeline/types";
import type { RelationCandidate, RulebookDocument } from "@/entities/rulebook/types";
import type {
  ReviewStats,
  ReviewTaskDetail,
  ReviewTaskKind,
  ReviewTaskStatus,
  RuleSummary,
  RuleVersion,
  TaskPage,
} from "@/entities/rule-version/types";
import type { Result } from "@/server/result";

/** A page of the review queue: one status, regulator and kind, or every one. */
export interface TaskQuery {
  status: ReviewTaskStatus | null;
  regulator: string | null;
  kind: ReviewTaskKind | null;
  cursor: string | null;
  limit: number;
}

/**
 * What the review screens read; every write goes through server/api/rulebook-write.ts. The
 * queue, a task and the stats change outside this server (the pipeline opens candidate tasks,
 * other analysts decide them), so they are read fresh.
 */
export interface ReviewTasksPort {
  /** A page of the queue, in the rulebook's order: by regulator, higher priority, then oldest. */
  tasks(query: TaskQuery): Promise<Result<TaskPage>>;
  /** One task with its version, citations, documents, audit, tasks and candidate. */
  task(taskId: string): Promise<Result<ReviewTaskDetail>>;
  stats(): Promise<Result<ReviewStats>>;
  /** A rulebook document with its clauses (it never changes under its id). */
  document(documentId: string): Promise<Result<RulebookDocument>>;
  /** The pipeline's record of a stored document, for the link to its file; 404 when none. */
  storedDocument(documentId: string): Promise<Result<DocumentDetail>>;
  /** The open relation candidates of one document. */
  openRelations(documentId: string): Promise<Result<RelationCandidate[]>>;
  /** The rules, for the keys a draft may join. */
  rules(): Promise<Result<RuleSummary[]>>;
  /** One rule's versions in any status. */
  versionsOf(ruleKey: string): Promise<Result<RuleVersion[]>>;
}
