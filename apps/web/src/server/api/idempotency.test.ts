import { render } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import {
  IDEMPOTENCY_KEY_FIELD,
  IDEMPOTENCY_KEY_HEADER,
  IDEMPOTENT_OPERATIONS,
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

describe("IDEMPOTENT_OPERATIONS", () => {
  it("is empty while no service route reads the header", () => {
    expect(IDEMPOTENT_OPERATIONS.size).toBe(0);
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
