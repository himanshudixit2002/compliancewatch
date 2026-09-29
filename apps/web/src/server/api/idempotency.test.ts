import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { render } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { SERVICES_WITH_SPECS, routeKey } from "@/shared/config/services";
import type { RouteRef } from "@/shared/config/services";
import {
  IDEMPOTENCY_KEY_FIELD,
  IDEMPOTENCY_KEY_HEADER,
  IDEMPOTENT_OPERATIONS,
  IDEMPOTENT_ROUTES,
  IdempotencyKeyInput,
  idempotencyHeaders,
  idempotencyKeyOf,
  isIdempotentOperation,
  newIdempotencyKey,
} from "./idempotency";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";
const ALLOWED: ReadonlySet<string> = new Set(["profile.register-business"]);

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.set(key, value);
  return data;
}

describe("newIdempotencyKey", () => {
  it("mints a fresh UUID each time", () => {
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first).toMatch(UUID);
    expect(second).toMatch(UUID);
    expect(first).not.toBe(second);
  });
});

const SPEC_DIR = join(resolve(__dirname, "../../../../.."), "packages/contracts/openapi");

interface SpecOperation {
  parameters?: { in?: string; name?: string; required?: boolean }[];
}

/** "service METHOD path" of every committed route that requires an Idempotency-Key header. */
function routesRequiringKey(): string[] {
  const keys: string[] = [];
  for (const service of SERVICES_WITH_SPECS) {
    const spec = JSON.parse(readFileSync(join(SPEC_DIR, `${service}.v1.json`), "utf8")) as {
      paths: Record<string, Record<string, SpecOperation>>;
    };
    for (const [path, operations] of Object.entries(spec.paths)) {
      for (const [method, operation] of Object.entries(operations)) {
        const header = (operation.parameters ?? []).find(
          (parameter) =>
            parameter.in === "header" &&
            parameter.name?.toLowerCase() === IDEMPOTENCY_KEY_HEADER.toLowerCase(),
        );
        if (header?.required === true) {
          keys.push(
            routeKey({ service, method: method.toUpperCase() as RouteRef["method"], path }),
          );
        }
      }
    }
  }
  return keys.sort();
}

describe("IDEMPOTENT_OPERATIONS", () => {
  it("names exactly the committed routes that require the header", () => {
    const listed = Object.values(IDEMPOTENT_ROUTES)
      .map((route) => routeKey(route))
      .sort();
    expect(listed).toEqual(routesRequiringKey());
    expect([...IDEMPOTENT_OPERATIONS].sort()).toEqual(Object.keys(IDEMPOTENT_ROUTES).sort());
    expect(isIdempotentOperation("profile.create-business")).toBe(true);
    expect(isIdempotentOperation("profile.add-registration")).toBe(true);
    expect(isIdempotentOperation("profile.register-business")).toBe(false);
  });

  it("answers by membership of the set it is given", () => {
    expect(isIdempotentOperation("profile.register-business", ALLOWED)).toBe(true);
    expect(isIdempotentOperation("identity.record-consents", ALLOWED)).toBe(false);
  });
});

describe("idempotencyKeyOf", () => {
  it("reads a UUID from the hidden field and ignores anything else", () => {
    expect(idempotencyKeyOf(form({ [IDEMPOTENCY_KEY_FIELD]: FORM_UUID }))).toBe(FORM_UUID);
    expect(idempotencyKeyOf(form({ [IDEMPOTENCY_KEY_FIELD]: "not a uuid" }))).toBeUndefined();
    expect(idempotencyKeyOf(form({ [IDEMPOTENCY_KEY_FIELD]: "x\r\nEvil: 1" }))).toBeUndefined();
    expect(idempotencyKeyOf(form({}))).toBeUndefined();
  });
});

describe("idempotencyHeaders", () => {
  it("sends nothing for an operation outside the set, whatever the form carries", () => {
    const data = form({ [IDEMPOTENCY_KEY_FIELD]: FORM_UUID });
    expect(idempotencyHeaders(data, "profile.register-business")).toEqual({});
    expect(idempotencyHeaders(data, "identity.record-consents", ALLOWED)).toEqual({});
  });

  it("sends the form's key for an allow-listed operation", () => {
    const data = form({ [IDEMPOTENCY_KEY_FIELD]: FORM_UUID });
    expect(idempotencyHeaders(data, "profile.register-business", ALLOWED)).toEqual({
      [IDEMPOTENCY_KEY_HEADER]: FORM_UUID,
    });
    expect(idempotencyHeaders(data, "profile.create-business")).toEqual({
      [IDEMPOTENCY_KEY_HEADER]: FORM_UUID,
    });
  });

  it("sends nothing when the allow-listed operation's form has no valid key", () => {
    expect(idempotencyHeaders(form({}), "profile.register-business", ALLOWED)).toEqual({});
    expect(
      idempotencyHeaders(
        form({ [IDEMPOTENCY_KEY_FIELD]: "12345" }),
        "profile.register-business",
        ALLOWED,
      ),
    ).toEqual({});
  });
});

describe("IdempotencyKeyInput", () => {
  it("renders a hidden input named after the field holding a UUID, new per render", () => {
    const first = render(createElement(IdempotencyKeyInput));
    const input = first.container.querySelector("input");
    expect(input?.getAttribute("type")).toBe("hidden");
    expect(input?.getAttribute("name")).toBe(IDEMPOTENCY_KEY_FIELD);
    expect(input?.getAttribute("value")).toMatch(UUID);
    const second = render(createElement(IdempotencyKeyInput));
    expect(second.container.querySelector("input")?.getAttribute("value")).not.toBe(
      input?.getAttribute("value"),
    );
  });
});
