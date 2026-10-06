import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { modelRouteFromDto } from "@/entities/llm/mappers";
import { modelRouteDto } from "@/test/llm-fixture";
import { editNote, modelRows } from "../model/registry";
import { ModelsView } from "./models-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.llm.models", href: "/admin/llm/models", label: "Model routes" },
];

describe("ModelsView", () => {
  it("shows each feature's route and names the variable behind an override", async () => {
    const rows = modelRows([
      modelRouteFromDto(modelRouteDto()),
      modelRouteFromDto(modelRouteDto({ feature: "smoke", fallback: null, source: "override" })),
    ]);
    const { container } = render(
      <ModelsView title="Model routes" crumbs={crumbs} rows={rows} note={editNote()} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Model routes" })).toBeDefined();
    const smoke = container.querySelector("[data-feature='smoke']");
    expect(smoke?.textContent).toContain("Set by the gateway's environment");
    expect(smoke?.textContent).toContain("CW_LLM_ROUTES__SMOKE");
    expect(container.querySelector("[data-feature='qa']")?.textContent).toContain(
      "example/model-b",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the table is empty", () => {
    render(<ModelsView title="Model routes" crumbs={crumbs} rows={[]} note={editNote()} />);
    expect(screen.getByRole("heading", { name: "The gateway reports no route" })).toBeDefined();
  });
});
