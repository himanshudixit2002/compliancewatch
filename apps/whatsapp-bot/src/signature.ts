import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Meta signs every webhook delivery: `X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw
 * body with the app secret>`. The comparison is constant-time so a wrong guess learns nothing.
 */
export function signBody(rawBody: string, appSecret: string): string {
  return "sha256=" + createHmac("sha256", appSecret).update(rawBody, "utf8").digest("hex");
}

export function verifySignature(
  rawBody: string,
  header: string | undefined,
  appSecret: string,
): boolean {
  if (!header || !appSecret) return false;
  const expected = Buffer.from(signBody(rawBody, appSecret), "utf8");
  const given = Buffer.from(header.trim(), "utf8");
  return expected.length === given.length && timingSafeEqual(expected, given);
}
