import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import type { SearchAction } from "./search-form";
import type { SearchResults } from "./search-shared";
import { SearchView } from "./search-view";

const CRUMBS = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.search", href: "/admin/rulebook/search", label: "Clause search" },
];

const RESULTS: SearchResults = {
  terms: ["clause"],
  hits: [
    {
      clauseId: EXAMPLE_CLAUSE_IDS.first,
      rank: 1,
      clauseRef: "en.p1",
      externalRef: "Example 1/2000",
      title: "Example document title",
      docTypeLabel: "Circular",
      regulator: "Example regulator",
      publishedAt: "2000-01-15",
      segments: [
        { text: "Example ", mark: false },
        { text: "clause", mark: true },
        { text: " text", mark: false },
      ],
      score: "0.0164",
      lexicalRank: 1,
      vectorRank: null,
      citedBy: [
        {
          ruleVersionId: EXAMPLE_VERSION_ID,
          href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
        },
      ],
      outOfForce: true,
      documentHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    },
  ],
};

describe("the clause search", () => {
  it("posts the words and filters, then lists the hits with each leg's rank and the words marked", async () => {
    let sent: [string, string][] = [];
    const action = vi.fn<SearchAction>(async (_state, formData) => {
      sent = [...formData.entries()].map(([key, value]) => [key, String(value)]);
      return { status: "ok", value: RESULTS };
    });
    const { container } = render(
      <SearchView title="Clause search" crumbs={CRUMBS} action={action} />,
    );
    expect(screen.getByText(/the vector search does not run from here/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Words/), "Example clause");
    await user.click(screen.getByLabelText("Circular"));
    await user.selectOptions(screen.getByLabelText("Hits"), "20");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Results" })).toBeDefined());
    expect(sent).toEqual(
      expect.arrayContaining([
        ["text", "Example clause"],
        ["doc_type", "circular"],
        ["k", "20"],
      ]),
    );
    expect(screen.getByText("1 clauses found")).toBeDefined();
    const hit = container.querySelector("[data-slot='search-hit']") as HTMLElement;
    expect(within(hit).getByText("1. Clause en.p1 of Example 1/2000")).toBeDefined();
    expect(hit.querySelector("mark")?.textContent).toBe("clause");
    expect((hit.querySelector("[data-rank='lexical']") as HTMLElement).textContent).toBe("1");
    expect((hit.querySelector("[data-rank='vector']") as HTMLElement).textContent).toBe(
      "Not found by this search",
    );
    expect(within(hit).getByText("Its rule is out of force on this date")).toBeDefined();
    expect(within(hit).getByRole("link", { name: EXAMPLE_VERSION_ID })).toBeDefined();
    expect(
      within(hit)
        .getByRole("link", { name: "Open clause en.p1 in its document" })
        .getAttribute("href"),
    ).toContain(`clause_id=${EXAMPLE_CLAUSE_IDS.first}`);
    // The words stay in the form after the search.
    expect((screen.getByLabelText(/^Words/) as HTMLTextAreaElement).value).toBe("Example clause");
    expect((screen.getByLabelText("Hits") as HTMLSelectElement).value).toBe("20");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says when nothing matched, and puts a refused field's message on it", async () => {
    const answers: Awaited<ReturnType<SearchAction>>[] = [
      { status: "error", fieldErrors: { text: ["Example field error"] } },
      { status: "ok", value: { terms: [], hits: [] } },
      {
        status: "error",
        problem: { type: "urn:example", title: "Example failure", correlationId: "req-example-5" },
      },
    ];
    render(
      <SearchView
        title="Clause search"
        crumbs={CRUMBS}
        action={vi.fn<SearchAction>(async () => answers.shift() ?? { status: "idle" })}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByText("Example field error")).toBeDefined());
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText(/^Words/)));
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "No clause matched" })).toBeDefined(),
    );
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("req-example-5"));
  });
});
