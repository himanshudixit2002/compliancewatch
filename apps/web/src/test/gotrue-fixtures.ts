/**
 * Recorded response shapes of Supabase Auth's GoTrue API (v2), as its reference documents them
 * and as supabase-js reads them, with synthetic values: a session (sign-in, verify, refresh and
 * factor verify answer one), the factor list, an enrolment, a challenge, and the error bodies of
 * the two shapes GoTrue uses. They stand in for the Supabase project until one exists; the
 * adapter's tests run every call against them (server/auth/supabase.test.ts).
 */
function base64url(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

/** A Supabase access token with the claims the adapter reads (aal, sub); unsigned here. */
export function gotrueAccessToken(claims: {
  sub: string;
  aal: "aal1" | "aal2";
  email?: string;
  phone?: string;
}): string {
  return `${base64url({ alg: "ES256", typ: "JWT", kid: "key-1" })}.${base64url({
    iss: "https://project.supabase.test/auth/v1",
    aud: "authenticated",
    exp: 1_790_679_600,
    iat: 1_790_676_000,
    role: "authenticated",
    session_id: "11111111-2222-4333-8444-555555555555",
    is_anonymous: false,
    ...claims,
  })}.signature`;
}

export const GOTRUE_USER_ID = "7d9c5e2a-1b3f-4c6d-8e9f-0a1b2c3d4e5f";

/** `POST /auth/v1/verify`, `POST /auth/v1/token?grant_type=refresh_token`, factor verify. */
export function gotrueSession(aal: "aal1" | "aal2" = "aal1") {
  return {
    access_token: gotrueAccessToken({ sub: GOTRUE_USER_ID, aal, phone: "919876543210" }),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: 1_790_679_600,
    refresh_token: aal === "aal2" ? "refresh-token-aal2-synthetic" : "refresh-token-synthetic",
    user: {
      id: GOTRUE_USER_ID,
      aud: "authenticated",
      role: "authenticated",
      email: "",
      phone: "919876543210",
      phone_confirmed_at: "2000-04-10T05:00:00Z",
      app_metadata: { provider: "phone", providers: ["phone"] },
      user_metadata: {},
      created_at: "2000-04-10T05:00:00Z",
      updated_at: "2000-04-10T05:00:00Z",
    },
  };
}

/** `GET /auth/v1/factors`: every factor, and the TOTP ones again. */
export const GOTRUE_FACTORS = {
  all: [
    {
      id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e",
      friendly_name: "Work phone",
      factor_type: "totp",
      status: "verified",
      created_at: "2000-04-10T05:00:00Z",
      updated_at: "2000-04-10T05:00:00Z",
    },
    {
      id: "1a2b3c4d-5e6f-4708-8192-a3b4c5d6e7f8",
      friendly_name: "Old phone",
      factor_type: "totp",
      status: "unverified",
      created_at: "2000-04-11T05:00:00Z",
      updated_at: "2000-04-11T05:00:00Z",
    },
    {
      id: "2b3c4d5e-6f70-4819-9203-b4c5d6e7f809",
      friendly_name: "Landline",
      factor_type: "phone",
      status: "verified",
      created_at: "2000-04-12T05:00:00Z",
      updated_at: "2000-04-12T05:00:00Z",
    },
  ],
  totp: [],
};

/** `POST /auth/v1/factors {factor_type: "totp"}`. */
export const GOTRUE_ENROLMENT = {
  id: "3c4d5e6f-7081-492a-a314-c5d6e7f8091a",
  type: "totp",
  friendly_name: "Work phone",
  totp: {
    qr_code:
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 21"><rect width="21" height="21" fill="#fff"/></svg>',
    secret: "JBSWY3DPEHPK3PXP",
    uri: "otpauth://totp/ComplianceWatch:example?secret=JBSWY3DPEHPK3PXP&issuer=ComplianceWatch",
  },
};

/** `POST /auth/v1/factors/{id}/challenge`. */
export const GOTRUE_CHALLENGE = {
  id: "4d5e6f70-8192-4a3b-b425-d6e7f8091a2b",
  type: "totp",
  expires_at: 1_790_676_300,
};

/** The error body of the OTP, verify and factor routes. */
export const GOTRUE_ERRORS = {
  invalidCode: { code: 403, error_code: "otp_expired", msg: "Token has expired or is invalid" },
  wrongCode: { code: 422, error_code: "validation_failed", msg: "Invalid OTP token" },
  rateLimited: {
    code: 429,
    error_code: "over_sms_send_rate_limit",
    msg: "For security purposes, you can only request this after 60 seconds.",
  },
  badPhone: { code: 422, error_code: "validation_failed", msg: "Invalid phone number format" },
  /** The token route answers OAuth's shape. */
  refreshRevoked: {
    error: "invalid_grant",
    error_description: "Invalid Refresh Token: Already Used",
  },
  unavailable: { code: 500, error_code: "unexpected_failure", msg: "Database error" },
};
