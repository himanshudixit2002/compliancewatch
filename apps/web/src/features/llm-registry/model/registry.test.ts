import { describe, expect, it } from "vitest";
import { modelRouteFromDto, promptFromDto } from "@/entities/llm/mappers";
import { modelRouteDto, promptDto } from "@/test/llm-fixture";
import { editNote, featureLabel, modelRows, overrideVariable, promptRows } from "./registry";

describe("promptRows", () => {
  it("orders prompts by name then version, flags one without eval cases and shortens the hash", () => {
    const rows = promptRows([
      promptFromDto(promptDto({ name: "example.second", version: "10" })),
      promptFromDto(
        promptDto({ name: "example.second", version: "2", eval_cases: 0, sha256: null }),
      ),
      promptFromDto(promptDto()),
    ]);
    expect(rows.map((row) => row.key)).toEqual([
      "example.prompt@1",
      "example.second@2",
      "example.second@10",
    ]);
    expect(rows[0]).toMatchObject({ unguarded: false, shortHash: "0123456789ab" });
    expect(rows[1]).toMatchObject({ unguarded: true, shortHash: null, sha256: null });
  });
});

describe("modelRows", () => {
  it("orders the routes by the gateway's features and names an override's variable", () => {
    const rows = modelRows([
      modelRouteFromDto(modelRouteDto({ feature: "smoke" })),
      modelRouteFromDto(modelRouteDto({ feature: "extraction", source: "override" })),
    ]);
    expect(rows.map((row) => row.feature)).toEqual(["extraction", "smoke"]);
    expect(rows[0]).toMatchObject({
      featureLabel: "Extraction",
      overridden: true,
      sourceLabel: "Set by the gateway's environment",
      variable: "CW_LLM_ROUTES__EXTRACTION",
      timeout: "30 s",
    });
    expect(rows[1]).toMatchObject({ overridden: false, sourceLabel: "Default", variable: null });
    expect(overrideVariable("qa")).toBe("CW_LLM_ROUTES__QA");
    expect(featureLabel("qa")).toBe("QA");
  });
});

describe("editNote", () => {
  it("says what prompt and model edits wait for, from the registry", () => {
    const note = editNote();
    expect(note.title).toBe("Prompt and model edits");
    expect(note.waitingFor.map((item) => `${item.method} ${item.path}`)).toEqual([
      "PUT /v1/llm-gateway/prompts/{name}",
      "PUT /v1/llm-gateway/models/{feature}",
    ]);
  });
});
