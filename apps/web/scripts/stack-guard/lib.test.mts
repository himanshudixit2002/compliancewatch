// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  SERVICES,
  decide,
  isLocalPort,
  parseStackRecord,
  targets,
  type GuardInput,
  type Target,
} from "./lib.mts";

/** The ten addresses of a stack on a base, as make web-e2e exports them. */
function stackEnv(base: number): Record<string, string> {
  return Object.fromEntries(
    SERVICES.map((service, index) => [
      `CW_WEB_${service.toUpperCase().replace(/-/g, "_")}_URL`,
      `http://localhost:${base + index + 1}`,
    ]),
  );
}

/** The processes make web-stack starts on a base, by service. */
function stackProcesses(base: number): Map<string, string | null> {
  return new Map(
    SERVICES.map((service, index) => {
      const pkg = service.replace(/-/g, "_");
      return [
        service,
        `uv run --package compliancewatch-${service} uvicorn ${pkg}.main:app --host 127.0.0.1 --port ${base + index + 1}`,
      ];
    }),
  );
}

function input(overrides: Partial<GuardInput> = {}): GuardInput {
  const list: Target[] = targets(stackEnv(9200));
  return {
    targets: list,
    answering: new Set(list.map((target) => target.url)),
    record: { store: "memory", base: 9200 },
    processes: stackProcesses(9200),
    allow: false,
    dir: "var/web-stack-example",
    ...overrides,
  };
}

describe("targets", () => {
  it("takes the addresses make web-e2e exports, once each", () => {
    const list = targets(stackEnv(9200));
    expect(list).toHaveLength(10);
    expect(list[0]).toEqual({ service: "identity", url: "http://localhost:9201" });
    expect(list.at(-1)).toEqual({ service: "pipeline", url: "http://localhost:9210" });
  });

  it("takes both the specs' and the app's defaults when no address is set", () => {
    const list = targets({ SERVICE_PORT_BASE: "9200" });
    expect(list.filter((target) => target.service === "pipeline").map((t) => t.url)).toEqual([
      "http://localhost:9210",
      "http://localhost:8010",
    ]);
    expect(targets({}).map((target) => target.url)).toContain("http://localhost:8001");
    const product = targets({ CW_E2E_PRODUCT_URL: "http://127.0.0.1:8080/" });
    expect(product.map((target) => target.url)).toContain("http://127.0.0.1:8080");
  });
});

describe("parseStackRecord", () => {
  it("reads the store and the base make web-stack wrote, and calls anything else unknown", () => {
    expect(parseStackRecord("store=memory\nbase=9200\n")).toEqual({ store: "memory", base: 9200 });
    expect(parseStackRecord("store=postgres\nbase=8000")).toEqual({
      store: "postgres",
      base: 8000,
    });
    expect(parseStackRecord("store=unknown\nbase=8000\n")).toEqual({
      store: "unknown",
      base: 8000,
    });
    expect(parseStackRecord("store=sqlite\n")).toEqual({ store: "unknown", base: null });
    expect(parseStackRecord("")).toEqual({ store: "unknown", base: null });
    expect(parseStackRecord(null)).toBeNull();
  });
});

describe("decide", () => {
  it("runs against the memory stack make web-stack recorded and runs", () => {
    expect(decide(input())).toEqual({ run: true, note: null });
  });

  it("runs when nothing answers, since nothing can be staged", () => {
    expect(decide(input({ answering: new Set(), record: null }))).toEqual({
      run: true,
      note: null,
    });
  });

  it("refuses a stack recorded as Postgres, and says how to run anyway", () => {
    const decision = decide(input({ record: { store: "postgres", base: 9200 } }));
    expect(decision.run).toBe(false);
    if (decision.run) return;
    expect(decision.message).toContain("var/web-stack-example/store says they run on Postgres");
    expect(decision.message).toContain("http://localhost:9201");
    expect(decision.message).toContain("a stored document cannot be deleted");
    expect(decision.message).toContain("set E2E_ALLOW_POSTGRES=1");
  });

  it("treats a running stack whose store is unknown, or not recorded at all, as Postgres", () => {
    const unknown = decide(input({ record: { store: "unknown", base: 9200 } }));
    expect(unknown.run === false && unknown.message).toContain("their store is unknown");
    const none = decide(input({ record: null }));
    expect(none.run === false && none.message).toContain(
      "nothing in var/web-stack-example says which store they use",
    );
  });

  it("refuses services a memory record does not describe: another base, or no live process of the stack", () => {
    const elsewhere = decide(input({ record: { store: "memory", base: 8000 } }));
    expect(elsewhere.run === false && elsewhere.message).toContain(
      "records a memory stack on 8001-8010, but these are not its running services",
    );
    const stopped = new Map(stackProcesses(9200));
    stopped.set("pipeline", null);
    const gone = decide(input({ processes: stopped }));
    expect(gone.run === false && gone.message).toContain("http://localhost:9210");
    const other = new Map(stackProcesses(9200));
    other.set("rulebook", "uv run uvicorn rulebook.main:app --port 9999");
    expect(decide(input({ processes: other })).run).toBe(false);
    // A service that does not answer is no matter, whatever its process.
    expect(
      decide(
        input({
          processes: stopped,
          answering: new Set(["http://localhost:9201", "http://localhost:9203"]),
        }),
      ).run,
    ).toBe(true);
  });

  it("runs against Postgres when E2E_ALLOW_POSTGRES=1 says so, and says what that means", () => {
    const decision = decide(input({ record: { store: "postgres", base: 9200 }, allow: true }));
    expect(decision.run).toBe(true);
    expect(decision.run && decision.note).toContain("What the specs stage there stays there");
  });
});

describe("isLocalPort", () => {
  it("knows this machine's addresses on a port", () => {
    expect(isLocalPort("http://localhost:9201", 9201)).toBe(true);
    expect(isLocalPort("http://127.0.0.1:9201/", 9201)).toBe(true);
    expect(isLocalPort("http://[::1]:9201", 9201)).toBe(true);
    expect(isLocalPort("http://localhost:9201", 9202)).toBe(false);
    expect(isLocalPort("http://example.test:9201", 9201)).toBe(false);
    expect(isLocalPort("not a url", 9201)).toBe(false);
  });
});
