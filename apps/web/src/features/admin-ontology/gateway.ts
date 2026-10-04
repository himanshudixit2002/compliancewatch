import "server-only";

import { readOntology, type OntologyContext } from "@/server/ontology";
import type { OntologyPort } from "./ports";

/**
 * `GET /v1/ontology` through server/ontology.ts: no tenant header (the ontology is the same for
 * every tenant) and cached an hour under `profile:ontology`, the lifetime the service states.
 */
export function ontologyGateway(ctx: OntologyContext = {}): OntologyPort {
  return { ontology: () => readOntology(ctx) };
}
