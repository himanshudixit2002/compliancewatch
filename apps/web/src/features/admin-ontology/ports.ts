import type { Ontology } from "@/entities/ontology/types";
import type { Result } from "@/server/result";

/** What the ontology browser reads: the ontology the profile service serves. */
export interface OntologyPort {
  ontology(): Promise<Result<Ontology>>;
}
