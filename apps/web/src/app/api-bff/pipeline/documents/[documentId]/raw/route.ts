import type { NextRequest } from "next/server";
import { gateHandler } from "@/server/bff/gate";
import { rawDocumentResponse } from "@/server/bff/raw-document";
import { screenById } from "@/shared/config/screens";

/**
 * A stored document's bytes, streamed from the pipeline's raw store (system.raw-document): the
 * shared gate first (server/bff/gate.ts: the session and the entry's roles), then the headers and
 * the refusals of server/bff/raw-document.ts. GET only; Next answers 405 to any other method.
 */
export const dynamic = "force-dynamic";

const SCREEN = screenById("system.raw-document");

interface Context {
  params: Promise<{ documentId: string }>;
}

export async function GET(request: NextRequest, { params }: Context): Promise<Response> {
  const gate = await gateHandler(SCREEN, request);
  if (!gate.ok) return gate.response;
  const { documentId } = await params;
  return rawDocumentResponse(request, documentId, gate.session);
}
