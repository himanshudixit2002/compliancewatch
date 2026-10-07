import type { NextRequest } from "next/server";
import { gateHandler } from "@/server/bff/gate";
import { uploadResponse } from "@/server/bff/upload";
import { screenById } from "@/shared/config/screens";

/**
 * An admin's upload of a document to a source, streamed on to the pipeline (system.uploads): the
 * shared gate first (server/bff/gate.ts: the origin, the session and the entry's roles), then the
 * write token, the limits, the form's fields and the plain refusals of server/bff/upload.ts. POST
 * only; Next answers 405 to any other method.
 */
export const dynamic = "force-dynamic";

const SCREEN = screenById("system.uploads");

interface Context {
  params: Promise<{ key: string }>;
}

export async function POST(request: NextRequest, { params }: Context): Promise<Response> {
  const gate = await gateHandler(SCREEN, request);
  if (!gate.ok) return gate.response;
  const { key } = await params;
  return uploadResponse(request, key, gate.session);
}
