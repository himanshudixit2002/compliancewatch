import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { promptFromDto } from "@/entities/llm/mappers";
import { promptDto } from "@/test/llm-fixture";
import { editNote, promptRows } from "../model/registry";
import { PromptsView } from "./prompts-view";

const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.llm.prompts", href: "/admin/llm/prompts", label: "Prompts" },
];

describe("PromptsView", () => {
  it("lists every prompt, flags one with no eval case and says what edits wait for", async () => {
    const rows = promptRows([
      promptFromDto(promptDto()),
      promptFromDto(promptDto({ name: "example.unguarded", eval_cases: 0, sha256: null })),
    ]);
    const { container } = render(
      <PromptsView title="Prompts" crumbs={crumbs} rows={rows} note={editNote()} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Prompts" })).toBeDefined();
    expect(screen.getByText("example.prompt@1")).toBeDefined();
    expect(container.querySelector("[data-prompt='example.prompt@1']")?.textContent).toContain("3");
    expect(screen.getByText("No eval case")).toBeDefined();
    expect(screen.getByRole("button", { name: "Copy the hash of example.prompt@1" })).toBeDefined();
    expect(screen.getByText("Prompt and model edits: not offered")).toBeDefined();
    expect(container.querySelector("[data-slot='edit-awaits']")?.textContent).toContain(
      "PUT /v1/llm-gateway/prompts/{name}",
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why the registry is empty", () => {
    render(<PromptsView title="Prompts" crumbs={crumbs} rows={[]} note={editNote()} />);
    expect(screen.getByRole("heading", { name: "The gateway serves no prompt" })).toBeDefined();
  });
});
