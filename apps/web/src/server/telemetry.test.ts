// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "./env";
import { resetFlagReader } from "./flags";
import {
  SERVICE_NAME,
  otelConfiguration,
  otlpEndpointConfigured,
  registerTelemetry,
  registeredTelemetry,
  resetTelemetryRegistration,
  telemetryPlan,
  type Register,
} from "./telemetry";
import { RedactingSpanProcessor } from "./telemetry-redaction";

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  resetEnvCache();
  resetTelemetryRegistration();
  await resetFlagReader();
});

function flagOn(): void {
  vi.stubEnv("CW_WEB_ENV", "test");
  vi.stubEnv("CW_WEB_FLAG_OTEL_ENABLED", "true");
}

describe("the telemetry plan", () => {
  it("registers nothing while the flag is off, its default", async () => {
    const register = vi.fn<Register>();
    const plan = await registerTelemetry(async () => register, {});
    expect(plan).toEqual({ enabled: false, exporting: false });
    expect(register).not.toHaveBeenCalled();
  });

  it("registers a tracer without a span processor when no OTLP endpoint is configured", async () => {
    flagOn();
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const register = vi.fn<Register>();
    const plan = await registerTelemetry(async () => register, {});
    expect(plan).toEqual({ enabled: true, exporting: false });
    expect(register).toHaveBeenCalledWith({ serviceName: SERVICE_NAME, spanProcessors: [] });
  });

  it("exports over OTLP when an endpoint is configured, every span redacted first", async () => {
    flagOn();
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const register = vi.fn<Register>();
    const env = { OTEL_EXPORTER_OTLP_ENDPOINT: "http://localhost:4318" };
    expect(await registerTelemetry(async () => register, env)).toEqual({
      enabled: true,
      exporting: true,
    });
    expect(register).toHaveBeenCalledWith({
      serviceName: SERVICE_NAME,
      spanProcessors: [expect.any(RedactingSpanProcessor), "auto"],
    });
    expect(await telemetryPlan({ OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: "http://example" })).toEqual({
      enabled: true,
      exporting: true,
    });
  });

  it("logs a failed registration and lets the server start", async () => {
    flagOn();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const plan = await registerTelemetry(async () => {
      throw new Error("Example load failure");
    }, {});
    expect(plan).toEqual({ enabled: false, exporting: false, failed: true });
    expect(registeredTelemetry()).toEqual(plan);
    expect(JSON.parse(String(warn.mock.calls[0]?.[0]))).toMatchObject({
      event: "telemetry_registration_failed",
      error: "Example load failure",
    });
  });

  it("reads an endpoint only when it has a value", () => {
    expect(otlpEndpointConfigured({ OTEL_EXPORTER_OTLP_ENDPOINT: " " })).toBe(false);
    expect(otlpEndpointConfigured({})).toBe(false);
    expect(otelConfiguration({ enabled: true, exporting: false }).spanProcessors).toEqual([]);
  });
});

describe("what registered", () => {
  it("is nothing before registration runs", () => {
    expect(registeredTelemetry()).toBeNull();
  });

  it("keeps the outcome for the process, so a later flag change shows only after a restart", async () => {
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    await registerTelemetry(async () => vi.fn<Register>(), {});
    expect(registeredTelemetry()).toEqual({ enabled: false, exporting: false });
    flagOn();
    expect((await telemetryPlan({})).enabled).toBe(true);
    expect(registeredTelemetry()).toEqual({ enabled: false, exporting: false });
  });

  it("is kept on globalThis, where another bundle of this module finds it", async () => {
    flagOn();
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const outcome = await registerTelemetry(async () => vi.fn<Register>(), {
      OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: "http://localhost:4318/v1/traces",
    });
    const shared = (globalThis as Record<symbol, unknown>)[
      Symbol.for("compliancewatch.web.telemetry")
    ];
    expect(shared).toEqual({ enabled: true, exporting: true });
    expect(shared).toBe(outcome);
  });
});
