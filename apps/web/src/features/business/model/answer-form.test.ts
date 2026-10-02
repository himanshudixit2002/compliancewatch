import { describe, expect, it } from "vitest";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { ANSWER_FIELDS, answerFieldErrors, isAttributeKey, readAnswerForm } from "./answer-form";

function form(entries: [string, string][]): FormData {
  const data = new FormData();
  for (const [key, value] of entries) data.append(key, value);
  return data;
}

const HIDDEN: [string, string][] = [
  [ANSWER_FIELDS.businessId, ENTITY_ID],
  [ANSWER_FIELDS.nodeId, REGISTRATION_ID],
  [ANSWER_FIELDS.key, "example_kind"],
];

describe("readAnswerForm", () => {
  it("reads the hidden fields, the state and every value", () => {
    const data = form([
      ...HIDDEN,
      [ANSWER_FIELDS.asOfFy, "2000-01"],
      [ANSWER_FIELDS.state, "known"],
      [ANSWER_FIELDS.value, "01"],
      [ANSWER_FIELDS.value, "02"],
    ]);
    data.append(ANSWER_FIELDS.value, new Blob(["x"]));
    expect(readAnswerForm(data)).toEqual({
      businessId: ENTITY_ID,
      nodeId: REGISTRATION_ID,
      key: "example_kind",
      asOfFy: "2000-01",
      state: "known",
      values: ["01", "02"],
    });
  });

  it("takes an empty year as none", () => {
    expect(readAnswerForm(form([...HIDDEN, [ANSWER_FIELDS.asOfFy, ""]]))?.asOfFy).toBeNull();
  });

  it("refuses a malformed hidden field", () => {
    expect(readAnswerForm(form(HIDDEN.slice(1)))).toBeNull();
    expect(
      readAnswerForm(form([...HIDDEN.slice(0, 2), [ANSWER_FIELDS.key, "Bad Key"]])),
    ).toBeNull();
    expect(readAnswerForm(form([...HIDDEN, [ANSWER_FIELDS.asOfFy, "2000"]]))).toBeNull();
    expect(
      readAnswerForm(
        form([
          [ANSWER_FIELDS.businessId, ENTITY_ID],
          [ANSWER_FIELDS.nodeId, "x"],
          [ANSWER_FIELDS.key, "k"],
        ]),
      ),
    ).toBeNull();
  });

  it("knows an attribute key", () => {
    expect(isAttributeKey("turnover_band")).toBe(true);
    expect(isAttributeKey("1band")).toBe(false);
  });
});

describe("answerFieldErrors", () => {
  it("puts the change list's value errors on the control and the rest on the form", () => {
    expect(
      answerFieldErrors({
        "changes.0.value": ["Example value message."],
        value: ["Example direct message."],
        "changes.0.as_of_fy": ["Example year message."],
      }),
    ).toEqual({
      value: ["Example value message.", "Example direct message."],
      form: ["Example year message."],
    });
    expect(answerFieldErrors(undefined)).toEqual({ value: [], form: [] });
  });
});
