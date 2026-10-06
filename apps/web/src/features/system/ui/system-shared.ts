/** The web server's own facts, as the system page shows them; no secret's value is among them. */
export interface WebFacts {
  environment: string;
  /** The sign-in provider CW_WEB_AUTH_PROVIDER names; null when none is configured. */
  authProvider: string | null;
  /** CW_WEB_BUILD_SHA; null for a development build. */
  build: string | null;
  requestTimeoutMs: number;
  /** Whether the rulebook's two tokens are set (never their values). */
  writeToken: boolean;
  reviewToken: boolean;
  flagProvider: { ok: true; name: string } | { ok: false; reason: string };
  /**
   * What OpenTelemetry registration did when this server started; null when no registration was
   * recorded in this process.
   */
  telemetry: { enabled: boolean; exporting: boolean; failed?: boolean } | null;
  node: string;
}
