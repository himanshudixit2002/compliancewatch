import type { NextRequest } from "next/server";
import { rawDocumentResponse } from "@/server/bff/raw-document";
import { verifySession } from "@/server/dal";

/**
 * A stored document's bytes, streamed from the pipeline's raw store (system.raw-document): the
 * gate, the headers and the refusals are server/bff/raw-document.ts's. GET only; Next answers 405
 * to any other method.
 */
export const dynamic = "force-dynamic";

interface Context {
  params: Promise<{ documentId: string }>;
}

export async function GET(request: NextRequest, { params }: Context): Promise<Response> {
  const { documentId } = await params;
  return rawDocumentResponse(request, documentId, await verifySession());
}
