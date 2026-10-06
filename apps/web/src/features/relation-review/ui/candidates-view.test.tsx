import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it } from "vitest";
import { relationCandidateFromDto } from "@/entities/rulebook/mappers";
import {
  EXAMPLE_CANDIDATE_ID,
  EXAMPLE_DOCUMENT_ID,
  relationCandidateDto,
} from "@/test/rulebook-fixture";
import { candidateQueueView, readCandidateQueue } from "../model/queue";
import { CandidatesView } from "./candidates-view";

const PATH = "/admin/rulebook/relations";
const crumbs = [
  { id: "admin.home", href: "/admin", label: "Internal tools" },
  { id: "admin.rulebook.relations", href: PATH, label: "Relation candidates" },
];

describe("CandidatesView", () => {
  it("lists the candidates with their target, evidence, scores and status", async () => {
    const read = readCandidateQueue({});
    const view = candidateQueueView(PATH, { status: "open", documentId: null, after: null }, [
      relationCandidateFromDto(relationCandidateDto()),
    ]);
    const { container } = render(
      <CandidatesView
        title="Relation candidates"
        crumbs={crumbs}
        pageHref={PATH}
        read={read}
        view={view}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Relation candidates" })).toBeDefined();
    expect(screen.getByRole("link", { name: "Extends deadline" }).getAttribute("href")).toBe(
      `${PATH}/${EXAMPLE_CANDIDATE_ID}?status=open`,
    );
    expect(
      screen
        .getByRole("navigation", { name: "Show candidates by status" })
        .querySelector("[aria-current='true']")?.textContent,
    ).toBe("Open");
    expect(screen.getByText("Quote match 100%")).toBeDefined();
    expect(screen.getByText("Issues: Target unaligned")).toBeDefined();
    expect(screen.getByText("Not aligned to an entity yet")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("says why a status is empty and keeps a document filter with a way to drop it", () => {
    const read = readCandidateQueue({ status: "approved", document: EXAMPLE_DOCUMENT_ID });
    render(
      <CandidatesView
        title="Relation candidates"
        crumbs={crumbs}
        pageHref={PATH}
        read={read}
        view={candidateQueueView(
          PATH,
          { status: "approved", documentId: EXAMPLE_DOCUMENT_ID, after: null },
          [],
        )}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "No approved candidate for this document" }),
    ).toBeDefined();
    expect(screen.getByText(/^This document has no candidate in this status/)).toBeDefined();
    expect(screen.queryByRole("heading", { name: "No candidate is approved yet" })).toBeNull();
    expect(screen.getByRole("link", { name: "Every document" }).getAttribute("href")).toBe(
      `${PATH}?status=approved`,
    );
    expect(screen.queryByRole("navigation", { name: "Pages of relation candidates" })).toBeNull();
  });

  it("says a status is empty everywhere only without a document or a page", () => {
    render(
      <CandidatesView
        title="Relation candidates"
        crumbs={crumbs}
        pageHref={PATH}
        read={readCandidateQueue({ status: "rejected" })}
        view={candidateQueueView(PATH, { status: "rejected", documentId: null, after: null }, [])}
      />,
    );
    expect(screen.getByRole("heading", { name: "No candidate is rejected yet" })).toBeDefined();
  });

  it("says a later page holds nothing more and always offers the first page", async () => {
    const read = readCandidateQueue({ document: EXAMPLE_DOCUMENT_ID, after: EXAMPLE_CANDIDATE_ID });
    const { container } = render(
      <CandidatesView
        title="Relation candidates"
        crumbs={crumbs}
        pageHref={PATH}
        read={read}
        view={candidateQueueView(PATH, read.filter, [])}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "No more open candidates after the previous page" }),
    ).toBeDefined();
    expect(screen.queryByRole("heading", { name: "No candidate waits for a decision" })).toBeNull();
    const pager = screen.getByRole("navigation", { name: "Pages of relation candidates" });
    expect(pager.querySelector("a")?.textContent).toBe("First page");
    expect(pager.querySelector("a")?.getAttribute("href")).toBe(
      `${PATH}?document=${EXAMPLE_DOCUMENT_ID}`,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("marks a malformed document id on its field and shows a failed read", async () => {
    const { container } = render(
      <CandidatesView
        title="Relation candidates"
        crumbs={crumbs}
        pageHref={PATH}
        read={readCandidateQueue({ document: "not-a-document" })}
        view={null}
        error={{ message: "Example outage", status: 503, requestId: "req-example-2" }}
      />,
    );
    expect(screen.getByText("This is not a document id (a UUID).")).toBeDefined();
    expect(screen.getByText("Example outage")).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
