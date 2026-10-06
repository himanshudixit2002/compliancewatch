import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { CitationList, type CitationView } from "./citation-list";

const READ: CitationView = {
  id: "c1",
  clauseRef: "en.p2",
  quote: "Example quoted clause text.",
  clauseText: "Example whole clause text.",
  documentTitle: "Example document title",
  documentRef: "Example 1/2000",
  sourceHref: "https://example.com/example.pdf",
  page: 3,
  verifiedAt: "2 Jan 2000",
};

describe("CitationList", () => {
  it("shows each quote with its clause, its document and the source to check", async () => {
    const { container } = render(
      <CitationList
        citations={[
          READ,
          {
            ...READ,
            id: "c2",
            clauseRef: "en.p4",
            clauseText: null,
            documentTitle: null,
            documentRef: null,
            sourceHref: null,
            page: null,
            verifiedAt: null,
          },
          { ...READ, id: "c3", documentRef: "", page: null, verifiedAt: "3 Jan 2000" },
        ]}
        empty="Example empty"
      />,
    );
    expect(
      screen.getByText("Clause en.p2 of Example document title (Example 1/2000)"),
    ).toBeDefined();
    expect(screen.getByText("Quote verified on 2 Jan 2000")).toBeDefined();
    expect(screen.getByText("Read the whole clause (page 3)")).toBeDefined();
    expect(container.querySelectorAll("[data-slot='clause-text']")).toHaveLength(2);
    const sources = screen.getAllByRole("link", { name: /Open the source document/ });
    expect(sources[0]?.getAttribute("href")).toBe("https://example.com/example.pdf");
    expect(sources[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByText("Clause en.p4")).toBeDefined();
    expect(screen.getByText("Quote verified")).toBeDefined();
    expect(screen.getByText(/could not be read from the rulebook just now/)).toBeDefined();
    expect(screen.getByText("Clause en.p2 of Example document title")).toBeDefined();
    expect(screen.getByText("Read the whole clause")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why there is nothing to show", () => {
    render(<CitationList citations={[]} empty="Example empty" />);
    expect(screen.getByText("Example empty")).toBeDefined();
  });
});
