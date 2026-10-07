import { describe, expect, it } from "vitest";
import { SUBSCRIBE_FIELDS, parseSubscribeForm } from "./subscribe-form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const KEYS = ["example_monthly", "example_yearly"];

describe("parseSubscribeForm", () => {
  it("reads an offered plan, the email and the name, trimmed", () => {
    expect(
      parseSubscribeForm(
        form({
          plan_key: "example_yearly",
          email: " owner@example.com ",
          name: " Example Traders ",
        }),
        KEYS,
      ),
    ).toEqual({
      ok: true,
      value: { planKey: "example_yearly", email: "owner@example.com", name: "Example Traders" },
    });
  });

  it("names every field that is missing or wrong", () => {
    expect(parseSubscribeForm(form({ plan_key: "other" }), KEYS)).toEqual({
      ok: false,
      fieldErrors: {
        [SUBSCRIBE_FIELDS.plan]: ["Choose one of the plans listed."],
        [SUBSCRIBE_FIELDS.email]: ["Enter the billing email."],
        [SUBSCRIBE_FIELDS.name]: ["Enter the billing name."],
      },
    });
    expect(
      parseSubscribeForm(
        form({ plan_key: "example_monthly", email: "owner", name: "x".repeat(201) }),
        KEYS,
      ),
    ).toEqual({
      ok: false,
      fieldErrors: {
        [SUBSCRIBE_FIELDS.email]: ["Enter an email address, such as name@example.com."],
        [SUBSCRIBE_FIELDS.name]: ["Use at most 200 characters."],
      },
    });
  });

  it("reads the units when given, and refuses anything but a whole number from 1 to 1000", () => {
    const valid = { plan_key: "example_monthly", email: "owner@example.com", name: "Example" };
    expect(parseSubscribeForm(form({ ...valid, quantity: " 3 " }), KEYS)).toEqual({
      ok: true,
      value: {
        planKey: "example_monthly",
        email: "owner@example.com",
        name: "Example",
        quantity: 3,
      },
    });
    expect(parseSubscribeForm(form({ ...valid, quantity: "" }), KEYS)).toEqual({
      ok: true,
      value: { planKey: "example_monthly", email: "owner@example.com", name: "Example" },
    });
    for (const quantity of ["0", "1001", "2.5", "-1", "two"]) {
      expect(parseSubscribeForm(form({ ...valid, quantity }), KEYS)).toEqual({
        ok: false,
        fieldErrors: { [SUBSCRIBE_FIELDS.quantity]: ["Enter a whole number from 1 to 1000."] },
      });
    }
  });
});
