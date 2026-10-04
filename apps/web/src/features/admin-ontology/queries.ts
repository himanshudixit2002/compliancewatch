import "server-only";

import type { ClientContext } from "@/server/api/services";
import { mapResult, type Result } from "@/server/result";
import { ontologyGateway } from "./gateway";
import { ontologyBrowserView, type OntologyBrowserView } from "./model/browser";

/** The browser's read: the ontology, grouped by level for the page. */
export async function getOntologyBrowser(
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<Result<OntologyBrowserView>> {
  const ontology = await ontologyGateway({ fetchImpl: deps.fetchImpl }).ontology();
  return mapResult(ontology, ontologyBrowserView);
}
