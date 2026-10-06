import type { NextRequest } from "next/server";
import { uploadResponse } from "@/server/bff/upload";
import { verifySession } from "@/server/dal";

/**
 * An admin's upload of a document to a source, streamed on to the pipeline (system.uploads): the
 * origin and role checks, the limits, the form's fields and the plain refusals are
 * server/bff/upload.ts's. POST only; Next answers 405 to any other method.
 */
export const dynamic = "force-dynamic";

interface Context {
  params: Promise<{ key: string }>;
}

export async function POST(request: NextRequest, { params }: Context): Promise<Response> {
  const { key } = await params;
  return uploadResponse(request, key, await verifySession());
}
