import "server-only";

import { cache } from "react";
import { ontologyFromDto } from "@/entities/ontology/mappers";
import type { Ontology } from "@/entities/ontology/types";
import { call } from "./api/client";
import { profileClient, type ClientContext } from "./api/services";
import { cachedRead, tags } from "./cache";
import { mapBody, type Result } from "./result";

/**
 * The ontology the screens word attributes with, read from the profile service's
 * `GET /v1/ontology`: the questions onboarding asks, the help lines, the labels of the allowed
 * values and the operators a rule may use per type. It is the same for every tenant and changes
 * only with a release, so the read carries no tenant header and is cached under one tag,
 * `profile:ontology`, for `ONTOLOGY_REVALIDATE_SECONDS`, the lifetime the service itself states
 * (`Cache-Control: max-age=3600`). The service's ETag and 304 serve a client that keeps its own
 * copy; this server keeps its copy in Next's data cache, and a release that changes the wording
 * is picked up within the hour, or at once after `updateTag(tags.profile.ontology())`.
 *
 * `getOntology()` is the per-request memo pages and actions call, so a page that renders several
 * views over the ontology reads it once.
 */
export const ONTOLOGY_REVALIDATE_SECONDS = 3600;

export type OntologyContext = Pick<ClientContext, "fetchImpl">;

export async function readOntology(ctx: OntologyContext = {}): Promise<Result<Ontology>> {
  const client = profileClient({ session: null, fetchImpl: ctx.fetchImpl });
  const result = await call(
    client.GET("/v1/ontology", {
      ...cachedRead([tags.profile.ontology()], ONTOLOGY_REVALIDATE_SECONDS),
    }),
  );
  return mapBody(result, ontologyFromDto);
}

/** The ontology for the current request, read once however many views need it. */
export const getOntology: () => Promise<Result<Ontology>> = cache(() => readOntology());
