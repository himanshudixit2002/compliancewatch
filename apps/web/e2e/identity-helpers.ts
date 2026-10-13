import { serviceUrl } from "./fixtures";

/**
 * An internal admin's headers for a spec that calls a service directly, on a route a person's
 * token opens (the engine's dry run and fan-out controls): identity signs a provider token for
 * an admin persona in the one development internal tenant, at aal2, and exchanges it at
 * `POST /sessions` for its own token. In header mode a service ignores the bearer, so the call
 * behaves as it did; in dual mode (`make web-stack AUTH=dual`, the CI job) those routes answer
 * 401 without it. The token is kept for the worker and minted again before it expires.
 */
interface MintedSession {
  headers: Record<string, string>;
  expiresAt: number;
}

const RENEW_MARGIN_SECONDS = 60;
let minted: Promise<MintedSession> | null = null;

export async function adminAuthHeaders(): Promise<Record<string, string>> {
  const current = minted === null ? null : await minted;
  if (current !== null && current.expiresAt - RENEW_MARGIN_SECONDS > Date.now() / 1000) {
    return current.headers;
  }
  const fresh = mintAdminSession();
  minted = fresh;
  return (await fresh).headers;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${serviceUrl("identity")}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`identity answered ${response.status} to ${path}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

async function mintAdminSession(): Promise<MintedSession> {
  const provider = await postJson<{ provider_token: string }>("/v1/identity/dev/provider-tokens", {
    email: "e2e-admin@fake.compliancewatch.invalid",
    aal: "aal2",
    tenant_kind: "internal",
    roles: ["admin"],
    display_name: "E2E admin",
  });
  const session = await postJson<{
    access_token: string;
    expires_in: number;
    tenant_id: string;
  }>("/v1/identity/sessions", { provider_token: provider.provider_token });
  return {
    headers: {
      authorization: `Bearer ${session.access_token}`,
      "x-tenant-id": session.tenant_id,
    },
    expiresAt: Date.now() / 1000 + session.expires_in,
  };
}
