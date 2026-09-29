import { describe, expect, it } from "vitest";
import { PREVIEWS, renderPreview } from "./previews";

describe("renderPreview", () => {
  it("returns null for no name or an unknown name", () => {
    expect(renderPreview(undefined)).toBeNull();
    expect(renderPreview("OntologyTable")).toBeNull();
  });

  it("only ever names components that exist", () => {
    for (const component of Object.values(PREVIEWS)) expect(typeof component).toBe("function");
  });
});
