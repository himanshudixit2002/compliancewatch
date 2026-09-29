import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import { CitationCard } from "./citation-card";

describe("CitationCard", () => {
  it("quotes the clause with its reference, document link and verified chip", async () => {
    const { container } = render(
      <CitationCard
        quote="Example clause text."
        clauseRef="Clause 4(2)"
        documentTitle="Example document"
        documentHref="/documents/1"
        verified
        verifiedBy="Reviewer A"
      />,
    );
    const card = container.querySelector("article");
    expect(card?.dataset.verified).toBe("true");
    expect(card?.querySelector("blockquote")?.textContent).toBe("Example clause text.");
    expect(screen.getByText("Clause 4(2)")).toBeDefined();
    expect(screen.getByRole("link", { name: "Example document" }).getAttribute("href")).toBe(
      "/documents/1",
    );
    expect(screen.getByText("Verified by Reviewer A").dataset.tone).toBe("success");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("warns when the citation is not verified and shows a title without a link", () => {
    render(
      <CitationCard
        quote="Example."
        clauseRef="Clause 1"
        documentTitle="Example document"
        verified={false}
      />,
    );
    expect(screen.getByText("Not verified").dataset.tone).toBe("warning");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Example document")).toBeDefined();
  });

  it("shows a plain verified chip without a reviewer name", () => {
    render(<CitationCard quote="Example." clauseRef="Clause 1" verified />);
    expect(screen.getByText("Verified")).toBeDefined();
  });
});
