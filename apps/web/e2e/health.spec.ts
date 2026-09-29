import { expect, test } from "./fixtures";

test("the health handler answers with status, version and commit", async ({ request }) => {
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  const body = (await response.json()) as { status: string; version: string; commit: string };
  expect(body.status).toBe("ok");
  expect(typeof body.version).toBe("string");
  expect(typeof body.commit).toBe("string");
});

test("every response carries the static security headers", async ({ request }) => {
  const response = await request.get("/");
  expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response.headers()["x-frame-options"]).toBe("DENY");
  expect(response.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(response.headers()["x-powered-by"]).toBeUndefined();
});
