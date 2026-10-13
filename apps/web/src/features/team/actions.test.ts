// @vitest-environment node
import { randomBytes } from "node:crypto";
import { redirect } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { resetEnvCache } from "@/server/env";
import { encryptSession } from "@/server/session";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeIdentity, type FixtureUser, type IdentityFixture } from "@/test/identity-fixture";
import { changeMemberRoles, disableMember, inviteMember } from "./actions";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
vi.mock("next/cache", () => ({ revalidatePath: vi.fn(), updateTag: vi.fn(), refresh: vi.fn() }));

const KEY = new Uint8Array(randomBytes(32));
const SECRET = Buffer.from(KEY).toString("base64");
const IDLE = { status: "idle" } as const;
const OWNER_PHONE = "+919876543210";

let identity: IdentityFixture;
let owner: FixtureUser;

class Redirected extends Error {
  constructor(readonly href: string) {
    super(`redirect ${href}`);
  }
}

function form(entries: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
}

async function signedInAs(
  user: FixtureUser,
  overrides: Partial<SessionClaims> = {},
): Promise<void> {
  const tenant = identity.tenants.get(user.tenantId);
  const claims: SessionClaims = {
    userId: user.id,
    tenantId: user.tenantId,
    tenantKind: tenant?.kind ?? "business",
    roles: [...user.roles],
    displayName: user.displayName,
    mfa: true,
    sv: user.sessionVersion,
    provider: "fake",
    ...sessionWindow(new Date(), 3600),
    cwToken: identity.accessToken(user),
    ...overrides,
  };
  fakeCookies.set("cw_session", await encryptSession(claims, KEY));
}

beforeEach(() => {
  fakeCookies.reset();
  identity = fakeIdentity();
  vi.stubGlobal("fetch", identity.fetchImpl);
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
  vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
  resetEnvCache();
  vi.mocked(redirect).mockImplementation((href) => {
    throw new Redirected(String(href));
  });
  owner = identity.provision({
    contact: { phone: OWNER_PHONE },
    kind: "business",
    roles: ["owner"],
    displayName: "Example owner",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  resetEnvCache();
  vi.mocked(redirect).mockReset();
});

describe("inviteMember", () => {
  it("invites with the bearer, then the page lists the member", async () => {
    await signedInAs(owner);
    const state = await inviteMember(
      IDLE,
      form({
        screen: "owner.settings.team",
        contact: "staff@example.test",
        displayName: "Example staff",
        roles: ["staff"],
      }),
    );
    expect(state).toEqual({
      status: "ok",
      value: undefined,
      message: "Example staff was invited.",
    });
    const sent = identity.requests.find(
      (request) => request.method === "POST" && request.pathname === "/v1/identity/users",
    );
    expect(sent?.headers.authorization).toBe(`Bearer ${identity.accessToken(owner)}`);
    expect(sent?.headers["x-tenant-id"]).toBe(owner.tenantId);
    expect(sent?.body).toEqual({
      email: "staff@example.test",
      display_name: "Example staff",
      roles: ["staff"],
    });
    expect(
      [...identity.users.values()].filter((user) => user.tenantId === owner.tenantId),
    ).toHaveLength(2);
  });

  it("names a role the kind lacks on the roles, and a taken address on the contact", async () => {
    await signedInAs(owner);
    const refused = await inviteMember(
      IDLE,
      form({ screen: "owner.settings.team", contact: "x@example.test", roles: ["analyst"] }),
    );
    expect(refused.status).toBe("error");
    if (refused.status === "error") expect(refused.fieldErrors?.roles?.[0]).toContain("analyst");
    const taken = await inviteMember(
      IDLE,
      form({ screen: "owner.settings.team", contact: OWNER_PHONE, roles: ["staff"] }),
    );
    expect(taken).toEqual({
      status: "error",
      fieldErrors: {
        contact: [
          "The sign-in provider already has an account for this address, and an invitation cannot claim it.",
        ],
      },
    });
  });

  it("runs the screen's gate: the wrong role is sent to /forbidden, no factor to verify it", async () => {
    const staff = identity.provision({
      contact: { phone: "+919812345678" },
      kind: "business",
      roles: ["staff"],
      displayName: "Example staff",
      tenantId: owner.tenantId,
    });
    await signedInAs(staff);
    await expect(
      inviteMember(
        IDLE,
        form({ screen: "owner.settings.team", contact: "x@example.test", roles: ["staff"] }),
      ),
    ).rejects.toMatchObject({ href: "/forbidden" });
    const admin = identity.provision({
      contact: { phone: "+919800000001" },
      kind: "internal",
      roles: ["admin"],
      displayName: "Example admin",
    });
    await signedInAs(admin, { mfa: false });
    await expect(
      inviteMember(
        IDLE,
        form({ screen: "admin.team", contact: "x@example.test", roles: ["analyst"] }),
      ),
    ).rejects.toMatchObject({ href: "/account/mfa?next=%2Fadmin%2Fteam" });
    expect(await inviteMember(IDLE, form({ screen: "nope" }))).toEqual({
      status: "error",
      formErrors: ["The form named a page this action does not serve."],
    });
  });
});

describe("changeMemberRoles and disableMember", () => {
  it("change roles and refuse to take the last admin's away", async () => {
    const staff = identity.provision({
      contact: { phone: "+919812345678" },
      kind: "business",
      roles: ["staff"],
      displayName: "Example staff",
      tenantId: owner.tenantId,
    });
    await signedInAs(owner);
    const changed = await changeMemberRoles(
      IDLE,
      form({
        screen: "owner.settings.team",
        userId: staff.id,
        roles: ["staff", "compliance_lead"],
      }),
    );
    expect(changed.status).toBe("ok");
    expect(identity.users.get(staff.id)?.roles).toEqual(["staff", "compliance_lead"]);
    expect(identity.users.get(staff.id)?.sessionVersion).toBe(1);
    const lastAdmin = await changeMemberRoles(
      IDLE,
      form({ screen: "owner.settings.team", userId: owner.id, roles: ["staff"] }),
    );
    expect(lastAdmin.status).toBe("error");
    if (lastAdmin.status === "error") {
      expect(lastAdmin.formErrors).toEqual([
        "This is the account's only admin. Make someone else an admin first.",
      ]);
      expect(lastAdmin.problem?.type).toContain("identity-last-admin");
    }
  });

  it("disable a member with a reason, never the signed-in person", async () => {
    const staff = identity.provision({
      contact: { phone: "+919812345678" },
      kind: "business",
      roles: ["staff"],
      displayName: "Example staff",
      tenantId: owner.tenantId,
    });
    await signedInAs(owner);
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      const disabled = await disableMember(
        IDLE,
        form({
          screen: "owner.settings.team",
          userId: staff.id,
          reason: "Left the company in April",
        }),
      );
      expect(disabled).toEqual({
        status: "ok",
        value: undefined,
        message: "Example staff was disabled. Their open sessions end.",
      });
      expect(identity.users.get(staff.id)?.status).toBe("disabled");
      const logged = info.mock.calls.map((call) => String(call[0]));
      const line = logged.find((entry) => entry.includes("team_member_disabled"));
      expect(line).toBeDefined();
      // What the admin wrote stays out of the process log; only its length is noted.
      expect(JSON.parse(line as string)).toMatchObject({
        event: "team_member_disabled",
        user_id: staff.id,
        by: owner.id,
        reason_length: "Left the company in April".length,
      });
      expect(logged.join("\n")).not.toContain("Left the company");
    } finally {
      info.mockRestore();
    }
    expect(
      await disableMember(
        IDLE,
        form({
          screen: "owner.settings.team",
          userId: owner.id,
          reason: "Trying to disable myself",
        }),
      ),
    ).toEqual({
      status: "error",
      formErrors: ["You cannot disable your own account."],
    });
    expect(
      (
        await disableMember(
          IDLE,
          form({ screen: "owner.settings.team", userId: staff.id, reason: "short" }),
        )
      ).status,
    ).toBe("error");
  });
});
