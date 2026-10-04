import { describe, expect, it } from "vitest";
import { templateCounts, templateRows } from "./templates";

const BASE = { metaName: "", placeholders: [], body: "Example body." };

describe("templateRows", () => {
  it("orders the templates by message, channel and language, with their approval in words", () => {
    const rows = templateRows([
      { ...BASE, key: "example_b", channel: "whatsapp", language: "hi", status: "submitted" },
      { ...BASE, key: "example_a", channel: "whatsapp", language: "en", status: "approved" },
      { ...BASE, key: "example_b", channel: "email", language: "en", status: "draft" },
      {
        ...BASE,
        key: "example_b",
        channel: "whatsapp",
        language: "en",
        status: "example_unknown",
        metaName: "cw_example_b_en",
        placeholders: ["business_name"],
      },
    ]);
    expect(rows.map((row) => `${row.key} ${row.channel} ${row.language}`)).toEqual([
      "example_a whatsapp en",
      "example_b email en",
      "example_b whatsapp en",
      "example_b whatsapp hi",
    ]);
    expect(rows.map((row) => [row.statusLabel, row.tone])).toEqual([
      ["Approved", "success"],
      ["Draft", "neutral"],
      ["Example unknown", "neutral"],
      ["Submitted", "info"],
    ]);
    expect(rows[2]).toMatchObject({
      channelLabel: "WhatsApp",
      languageLabel: "English",
      metaName: "cw_example_b_en",
      placeholders: ["business_name"],
    });
    expect(templateCounts(rows)).toEqual({ templates: 4, keys: 2 });
  });
});
