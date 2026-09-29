import { describe, expect, it } from "vitest";
import {
  epochSeconds,
  expiresAtDate,
  isSessionExpired,
  secondsUntilExpiry,
  sessionWindow,
  toSessionDto,
} from "./mappers";
import type { SessionClaims } from "./types";

const NOW = new Date("2026-09-29T10:00:00.500Z");

const claims: SessionClaims = {
  userId: "00000000-0000-4000-8000-000000000001",
  tenantId: "00000000-0000-4000-8000-000000000002",
  tenantKind: "business",
  roles: ["owner"],
  displayName: "Example owner",
  mfa: false,
  sv: 1,
  provider: "fake",
  issuedAt: epochSeconds(NOW),
  expiresAt: epochSeconds(NOW) + 3600,
  cwToken: "token-value-that-must-not-render",
  cwTokenExpiresAt: epochSeconds(NOW) + 600,
  providerRefreshToken: "refresh-value-that-must-not-render",
  checkedAt: epochSeconds(NOW),
  analyticsConsent: true,
};

describe("toSessionDto", () => {
  it("keeps the facts and drops every token field", () => {
    const dto = toSessionDto(claims);
    expect(dto).toEqual({
      userId: claims.userId,
      tenantId: claims.tenantId,
      tenantKind: "business",
      roles: ["owner"],
      displayName: "Example owner",
      mfa: false,
      provider: "fake",
      issuedAt: claims.issuedAt,
      expiresAt: claims.expiresAt,
    });
    expect(JSON.stringify(dto)).not.toContain("token");
    expect(JSON.stringify(dto)).not.toContain("refresh");
  });
});

describe("session time helpers", () => {
  it("count whole seconds and build the issue and expiry window", () => {
    expect(epochSeconds(NOW)).toBe(1_790_676_000);
    expect(sessionWindow(NOW, 28_800)).toEqual({
      issuedAt: 1_790_676_000,
      expiresAt: 1_790_704_800,
    });
    expect(() => sessionWindow(NOW, 0)).toThrow(/positive number of seconds/);
    expect(() => sessionWindow(NOW, 1.5)).toThrow(/positive number of seconds/);
  });

  it("report the time left and expiry, never negative", () => {
    expect(secondsUntilExpiry(claims, NOW)).toBe(3600);
    expect(isSessionExpired(claims, NOW)).toBe(false);
    const later = new Date(NOW.getTime() + 3600 * 1000);
    expect(secondsUntilExpiry(claims, later)).toBe(0);
    expect(isSessionExpired(claims, later)).toBe(true);
    expect(secondsUntilExpiry(claims, new Date(later.getTime() + 60_000))).toBe(0);
    expect(expiresAtDate(claims).toISOString()).toBe("2026-09-29T11:00:00.000Z");
  });
});
