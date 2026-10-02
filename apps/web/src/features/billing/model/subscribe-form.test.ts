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
});
