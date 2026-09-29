import { render, screen, within } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { beforeAll, describe, expect, it } from "vitest";
import { documentFromDto } from "@/entities/rulebook/mappers";
import { EXAMPLE_CLAUSE_IDS, documentDto } from "@/test/rulebook-fixture";
import { toDocumentView } from "../model/document-view";
import type { HighlightRequest } from "../model/highlight-request";
import { DocumentView } from "./document-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.documents", href: "/admin/rulebook/documents", label: "Documents" },
  { id: "admin.rulebook.document", href: "/admin/rulebook/documents/x", label: "Example 1/2000" },
];

beforeAll(() => {
  // jsdom lays nothing out; the viewer scrolls the marked clause into view on open.
  Element.prototype.scrollIntoView = () => {};
});

function renderView(request: HighlightRequest | "invalid" | null = null, overrides = {}) {
  const view = toDocumentView(documentFromDto(documentDto(overrides)), request);
  return render(<DocumentView view={view} crumbs={CRUMBS} />);
}

describe("DocumentView", () => {
  it("shows the source facts and every clause with its anchor and page", async () => {
    const { container } = renderView();
    expect(screen.getByRole("heading", { level: 1, name: "Example document title" })).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" }).textContent).toContain(
      "Example 1/2000",
    );
    const source = screen.getByRole("link", { name: /example-document\.pdf/ });
    expect(source.getAttribute("target")).toBe("_blank");
    expect(source.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByRole("button", { name: "Copy the sha256" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Clauses (3)" })).toBeDefined();
    const items = container.querySelectorAll("[data-slot='clause-list'] > li");
    expect([...items].map((item) => item.id)).toEqual([
      "clause-en.p1",
      "clause-en.p2",
      "clause-en.p3",
    ]);
    const third = items[2] as HTMLElement;
    expect(within(third).getByRole("link", { name: "Clause en.p3" }).getAttribute("href")).toBe(
      "#clause-en.p3",
    );
    expect(third.querySelector("[data-slot='clause-page']")?.textContent).toBe("Page 2");
    expect(items[1]?.querySelector("[data-slot='clause-page']")?.textContent).toBe(
      "Page not recorded",
    );
    expect(container.querySelector("mark")).toBeNull();
    expect(container.querySelector("[data-slot='highlight-note']")).toBeNull();
    const list = container.querySelector<HTMLElement>("[data-slot='clause-list']");
    expect(await runAxe(list as HTMLElement)).toHaveNoViolations();
  });

  it("marks the span a link asks for and says what was marked", async () => {
    const { container } = renderView({
      clauseId: EXAMPLE_CLAUSE_IDS.third,
      span: { start: 8, end: 14 },
    });
    const marked = container.querySelector<HTMLElement>("[data-marked='span']");
    expect(marked?.id).toBe("clause-en.p3");
    expect(marked?.querySelector("mark")?.textContent).toBe("clause");
    expect(marked?.querySelector("[data-slot='clause-text']")?.textContent).toBe(
      "Example Marked text starts: clause Marked text ends. text on the second page.",
    );
    const note = container.querySelector<HTMLElement>("[data-slot='highlight-note']");
    expect(note?.dataset.kind).toBe("span");
    expect(note?.textContent).toContain("clause en.p3 is the span from 8 to 14");
    expect(await runAxe(marked as HTMLElement)).toHaveNoViolations();
  });

  it("marks the whole clause with a warning when the span does not fit", () => {
    const { container } = renderView({
      clauseId: EXAMPLE_CLAUSE_IDS.first,
      span: { start: 3, end: 999 },
    });
    const marked = container.querySelector<HTMLElement>("[data-marked='clause']");
    expect(marked?.querySelector("mark")?.textContent).toBe(
      "Example clause text that opens the document.",
    );
    expect(screen.getByText("The span did not match")).toBeDefined();
  });

  it("marks a whole clause on request, and says when a clause or a link is not usable", () => {
    const whole = renderView({ clauseId: EXAMPLE_CLAUSE_IDS.second });
    expect(whole.container.querySelector("[data-marked='clause']")?.id).toBe("clause-en.p2");
    expect(screen.getByText("Clause en.p2 is marked, as the link asked.")).toBeDefined();
    whole.unmount();
    const missing = renderView({ clauseId: "00000000-0000-5000-8000-00000000ffff" });
    expect(screen.getByText("The clause is not in this document")).toBeDefined();
    expect(missing.container.querySelector("mark")).toBeNull();
    missing.unmount();
    renderView("invalid");
    expect(screen.getByText("The link's mark is malformed")).toBeDefined();
  });

  it("says when the document holds no clauses", () => {
    renderView(null, { clauses: [] });
    expect(screen.getByText("The rulebook holds no clauses for this document.")).toBeDefined();
    expect(screen.queryByRole("form", { name: "Jump to a clause" })).toBeNull();
  });
});
