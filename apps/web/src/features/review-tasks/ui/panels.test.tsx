import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { ontologyFixture } from "@/test/ontology-fixture";
import { EXAMPLE_CLAUSE_IDS } from "@/test/rulebook-fixture";
import { EXAMPLE_ANALYST_ID, EXAMPLE_OTHER_VERSION_ID } from "@/test/rule-version-fixture";
import { EXAMPLE_RELATION_CANDIDATE_ID } from "@/test/review-task-fixture";
import type { WriteAction } from "@/shared/ui/write-outcome";
import { ClaimPanel } from "./claim-panel";
import { ClauseTextsProvider } from "./clause-texts";
import { DecidePanel } from "./decide-panel";
import { DraftPanel } from "./draft-panel";
import { EditPanel, isFormField } from "./edit-panel";
import {
  relationField,
  type ContentValues,
  type DraftForm,
  type EditForm,
  type WriteResult,
} from "./form-shared";

const ONTOLOGY = ontologyFixture();

const VALUES: ContentValues = {
  title: "Example rule title",
  summary: "Example summary.",
  effectiveFrom: "2000-04-01",
  effectiveTo: "",
  frequency: "monthly",
  dueDay: "20",
  dueMonthOffset: "0",
  templateTitle: "Example obligation",
  templateSteps: "Example first step",
  templateDueInDays: "",
  templateEvidence: "example_evidence",
  todo: "Example question?",
  specification: { all_of: [{ attribute: "example_kind", operator: "eq", value: "first" }] },
};

const CLAUSES = [
  {
    value: EXAMPLE_CLAUSE_IDS.first,
    label: "en.p1 (Example 1/2000): Example clause text that opens the document.",
  },
];

/** The clause texts the page sends once, which the citation rows check a quote against. */
const TEXTS = { [EXAMPLE_CLAUSE_IDS.first]: "Example clause text that opens the document." };

function done(
  message: string,
  details: string[] = [],
): Awaited<ReturnType<WriteAction<WriteResult>>> {
  return { status: "ok", message, value: { kind: "done", message, details, links: [] } };
}

function sentOf(formData: FormData): Record<string, string> {
  return Object.fromEntries([...formData.entries()].map(([key, value]) => [key, String(value)]));
}

describe("ClaimPanel", () => {
  it("claims an open task and keeps the answer when the page renders the claim", async () => {
    const action = vi.fn<WriteAction<WriteResult>>(async () => done("Example claimed."));
    const user = userEvent.setup();
    const { container, rerender } = render(
      <ClaimPanel action={action} claim={{ state: "open", canClaim: true }} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(screen.getByRole("button", { name: "Claim this task" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Example claimed."),
    );
    rerender(
      <ClaimPanel action={action} claim={{ state: "mine", at: "1 May 2000, 10:30 am IST" }} />,
    );
    expect(screen.getByText("You claimed this task on 1 May 2000, 10:30 am IST.")).toBeDefined();
    expect(screen.getByRole("status").textContent).toContain("Example claimed.");
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("names someone else's claim, and says when the task is decided", () => {
    const action = vi.fn<WriteAction<WriteResult>>();
    const { rerender, container } = render(
      <ClaimPanel
        action={action}
        claim={{
          state: "other",
          by: { userId: EXAMPLE_ANALYST_ID, you: false },
          at: "1 May 2000, 10:30 am IST",
        }}
      />,
    );
    expect(container.textContent).toContain(
      `Claimed by ${EXAMPLE_ANALYST_ID} on 1 May 2000, 10:30 am IST. Only they draft and edit it`,
    );
    rerender(<ClaimPanel action={action} claim={{ state: "decided" }} />);
    expect(screen.getByText("This task is decided.")).toBeDefined();
    rerender(<ClaimPanel action={action} claim={{ state: "open", canClaim: false }} />);
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<ClaimPanel action={action} claim={{ state: "mine", at: null }} />);
    expect(screen.getByText("You claimed this task.")).toBeDefined();
  });
});

describe("EditPanel", () => {
  const FORM: EditForm = { initial: VALUES, clauseOptions: CLAUSES, revision: "r1" };

  it("sends every field with the value it was rendered with, the citations added and the note", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example saved.", ["Changed: Title."]);
    });
    const user = userEvent.setup();
    const { container } = render(
      <ClauseTextsProvider texts={TEXTS}>
        <EditPanel action={action} form={FORM} blocked={null} ontology={ONTOLOGY} />
      </ClauseTextsProvider>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
    const title = screen.getByLabelText(/^Title/);
    await user.clear(title);
    await user.type(title, "Example new title");
    await user.click(screen.getByRole("button", { name: "Add a citation" }));
    await user.selectOptions(
      screen.getByLabelText(/^Clause of citation 1/),
      EXAMPLE_CLAUSE_IDS.first,
    );
    const quote = screen.getByLabelText(/^Quote of citation 1/);
    await user.type(quote, "clause text that opens");
    expect(screen.getByText("The clause holds this quote word for word.")).toBeDefined();
    await user.type(quote, " not");
    expect(screen.getByText(/does not hold this quote word for word/)).toBeDefined();
    await user.type(screen.getByLabelText(/^Why \(for the audit\)/), "Example why");
    await user.click(screen.getByRole("button", { name: "Save the draft" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Example saved."));
    expect(sent[0]).toMatchObject({
      title: "Example new title",
      "base:title": "Example rule title",
      summary: "Example summary.",
      "base:summary": "Example summary.",
      "recurrence.frequency": "monthly",
      "base:recurrence.frequency": "monthly",
      "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
      "citations.0.quote": "clause text that opens not",
      note: "Example why",
    });
    expect(JSON.parse(sent[0]?.specification ?? "")).toEqual(VALUES.specification);
    expect(JSON.parse(sent[0]?.["base:specification"] ?? "")).toEqual(VALUES.specification);
    expect(screen.getByText("Changed: Title.")).toBeDefined();
  });

  it("sends an edit beside an untouched condition with flagged parts, which it leaves alone", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example saved.");
    });
    // A stored value the ontology does not offer: the editor flags it, but nobody touched it.
    const flagged = {
      ...FORM,
      initial: {
        ...VALUES,
        specification: {
          all_of: [{ attribute: "example_kind", operator: "eq", value: "nowhere" }],
        },
      },
    };
    const user = userEvent.setup();
    render(<EditPanel action={action} form={flagged} blocked={null} ontology={ONTOLOGY} />);
    await user.type(screen.getByLabelText(/^Summary/), " Example more.");
    await user.click(screen.getByRole("button", { name: "Save the draft" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    // Let the first save settle before the condition changes: on a slow runner the clicks below
    // overlapped it, and a second save went out.
    await waitFor(() =>
      expect(
        screen.getAllByRole("status").some((node) => node.textContent?.includes("Example saved.")),
      ).toBe(true),
    );
    expect(sent[0]?.specification).toBe(sent[0]?.["base:specification"]);
    // Once the condition changes, its flagged parts hold the form back.
    await user.click(screen.getByRole("button", { name: "Add a condition to Group 1" }));
    await user.click(screen.getByRole("button", { name: "Save the draft" }));
    await waitFor(() => expect(screen.getByText("Choose an attribute.")).toBeDefined());
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("keeps a condition with shape problems from being sent and moves focus to the first", async () => {
    const action = vi.fn<WriteAction<WriteResult>>();
    const user = userEvent.setup();
    render(<EditPanel action={action} form={FORM} blocked={null} ontology={ONTOLOGY} />);
    await user.click(screen.getByRole("button", { name: "Add a condition to Group 1" }));
    await user.click(screen.getByRole("button", { name: "Save the draft" }));
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByText("Choose an attribute.")).toBeDefined();
    await waitFor(() => expect(document.activeElement?.getAttribute("aria-invalid")).toBe("true"));
  });

  it("shows the fields' refusals under them and the rest in the answer", async () => {
    const action = vi.fn<WriteAction<WriteResult>>(async () => ({
      status: "error",
      problem: {
        type: "urn:example",
        title: "The draft is incomplete",
        correlationId: "example-id",
      },
      fieldErrors: { title: ["Enter a title."], "edits.unknown": ["Example other field"] },
      formErrors: ["title: missing"],
    }));
    const user = userEvent.setup();
    render(<EditPanel action={action} form={FORM} blocked={null} ontology={ONTOLOGY} />);
    await user.click(screen.getByRole("button", { name: "Save the draft" }));
    await waitFor(() => expect(screen.getByText("The draft is incomplete")).toBeDefined());
    expect(screen.getByText("Enter a title.")).toBeDefined();
    expect(screen.getByText("title: missing")).toBeDefined();
    expect(screen.getByText("Example other field")).toBeDefined();
    expect(isFormField(relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target"))).toBe(true);
    expect(isFormField(relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take"))).toBe(true);
    expect(isFormField("relation_candidates")).toBe(true);
    expect(isFormField("edits.unknown")).toBe(false);
  });

  it("says why the draft cannot be edited here", () => {
    render(
      <EditPanel
        action={vi.fn<WriteAction<WriteResult>>()}
        form={null}
        blocked="Example reason it is not edited"
        ontology={ONTOLOGY}
      />,
    );
    expect(screen.getByText("Example reason it is not edited")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Save the draft" })).toBeNull();
  });
});

describe("DraftPanel", () => {
  const FORM: DraftForm = {
    initial: { ...VALUES, todo: "" },
    ruleKey: "example_suggested_rule",
    suggestedKnown: false,
    regulator: "example_regulator",
    ruleKeys: ["example_rule"],
    relations: [
      {
        candidateId: EXAMPLE_RELATION_CANDIDATE_ID,
        label: "Supersedes: EXAMPLE-1",
        evidenceQuote: "Example clause text",
        needsTarget: true,
        targetOptions: [{ value: EXAMPLE_OTHER_VERSION_ID, label: "example_rule v1 (Published)" }],
      },
    ],
    relationsError: null,
    clauseOptions: CLAUSES,
    proposedCitations: [{ clauseRef: "en.p1", quote: "Example clause text that opens" }],
    revision: "r1",
  };

  it("drafts into a new rule, citing the analyst's own quotes, with a relation and its version", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example drafted.");
    });
    const user = userEvent.setup();
    const { container } = render(
      <DraftPanel action={action} form={FORM} blocked={null} ontology={ONTOLOGY} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
    expect(screen.getByRole("checkbox", { name: "Start a new rule with this key" })).toHaveProperty(
      "ariaChecked",
      "true",
    );
    await user.selectOptions(screen.getByLabelText(/^Where the new rule applies/), "entity");
    expect(screen.getByText("Cite the candidate's quotes (1)")).toBeDefined();
    await user.click(screen.getByRole("radio", { name: "Cite quotes of my own instead" }));
    await user.click(screen.getByRole("button", { name: "Add a citation" }));
    await user.selectOptions(
      screen.getByLabelText(/^Clause of citation 1/),
      EXAMPLE_CLAUSE_IDS.first,
    );
    await user.type(screen.getByLabelText(/^Quote of citation 1/), "Example clause text");
    await user.click(screen.getByRole("checkbox", { name: /Supersedes: EXAMPLE-1/ }));
    await user.selectOptions(
      screen.getByLabelText(/^The version it points at/),
      EXAMPLE_OTHER_VERSION_ID,
    );
    await user.click(screen.getByRole("button", { name: "Draft the version" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Example drafted."),
    );
    expect(sent[0]).toMatchObject({
      rule_key: "example_suggested_rule",
      new_rule: "on",
      "new_rule.regulator": "example_regulator",
      "new_rule.level": "entity",
      citations_mode: "own",
      "citations.0.clause_id": EXAMPLE_CLAUSE_IDS.first,
      "citations.0.quote": "Example clause text",
      [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "take")]: "on",
      [relationField(EXAMPLE_RELATION_CANDIDATE_ID, "target")]: EXAMPLE_OTHER_VERSION_ID,
      "edits.title": "Example rule title",
      "base:edits.title": "Example rule title",
    });
  });

  it("drafts into a rule that has the key, with the candidate's quotes and no relation", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example drafted.");
    });
    const user = userEvent.setup();
    render(
      <DraftPanel
        action={action}
        form={{ ...FORM, ruleKey: "example_rule", suggestedKnown: true, relations: [] }}
        blocked={null}
        ontology={ONTOLOGY}
      />,
    );
    expect(
      screen.getByText("A rule has this key: the version becomes its next one."),
    ).toBeDefined();
    expect(screen.getByText("The document has no open relation candidate.")).toBeDefined();
    await user.click(screen.getByRole("button", { name: "Draft the version" }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    expect(sent[0]).toMatchObject({
      rule_key: "example_rule",
      new_rule: "",
      citations_mode: "candidate",
    });
  });

  it("sends a relation ticked past the fiftieth row, and shows the errors on its row", async () => {
    const candidate = (n: number) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
    const relations = Array.from({ length: 60 }, (_, index) => ({
      candidateId: candidate(index + 1),
      label: `Refers to: EXAMPLE-${index + 1}`,
      evidenceQuote: "Example clause text",
      needsTarget: false,
      targetOptions: [{ value: EXAMPLE_OTHER_VERSION_ID, label: "example_rule v1 (Published)" }],
    }));
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return {
        status: "error",
        fieldErrors: {
          [relationField(candidate(55), "take")]: ["Example row refusal"],
          relation_candidates: ["Example list refusal"],
        },
      };
    });
    const user = userEvent.setup();
    render(
      <DraftPanel action={action} form={{ ...FORM, relations }} blocked={null} ontology={null} />,
    );
    await user.click(screen.getByRole("checkbox", { name: /Refers to: EXAMPLE-55(?!\d)/ }));
    await user.click(screen.getByRole("button", { name: "Draft the version" }));
    await waitFor(() => expect(action).toHaveBeenCalled());
    const taken = Object.keys(sent[0] ?? {}).filter((name) => name.endsWith(".take"));
    expect(taken).toEqual([relationField(candidate(55), "take")]);
    const row = screen.getByRole("checkbox", { name: /Refers to: EXAMPLE-55(?!\d)/ });
    await waitFor(() => expect(row.getAttribute("aria-invalid")).toBe("true"));
    expect(document.getElementById(row.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Example row refusal",
    );
    expect(screen.getByText("Example list refusal")).toBeDefined();
  });

  it("says why no version can be drafted, and when the relations could not be read", () => {
    const { rerender } = render(
      <DraftPanel
        action={vi.fn<WriteAction<WriteResult>>()}
        form={null}
        blocked="Example reason"
        ontology={null}
      />,
    );
    expect(screen.getByText("Example reason")).toBeDefined();
    rerender(
      <DraftPanel
        action={vi.fn<WriteAction<WriteResult>>()}
        form={{
          ...FORM,
          relations: [],
          relationsError: { message: "Example failure", requestId: "example-id" },
        }}
        blocked={null}
        ontology={null}
      />,
    );
    expect(screen.getByText("Example failure")).toBeDefined();
  });
});

describe("DecidePanel", () => {
  const VIEW = {
    candidateTask: false,
    drafted: true,
    canApprove: true,
    approveBlocked: null,
    canReturn: true,
    returnBlocked: null,
    canReject: true,
    rejectBlocked: null,
    highImpact: false,
  };
  const APPROVALS = {
    count: 1,
    required: 2,
    approvers: [{ userId: EXAMPLE_ANALYST_ID, you: true }],
    waitingForAnother: true,
  };

  it("approves as high impact after the dialog says what the rulebook records", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example approval recorded.");
    });
    const user = userEvent.setup();
    const { container } = render(<DecidePanel action={action} view={VIEW} approvals={APPROVALS} />);
    expect(container.querySelector("[data-slot='approvals']")?.textContent).toContain(
      "1 of 2 approvals in this round. A second, different reviewer completes it.you",
    );
    expect(await runAxe(container)).toHaveNoViolations();
    await user.click(screen.getByRole("checkbox", { name: /Mark it high impact/ }));
    await user.type(screen.getByLabelText(/^Note \(optional\)/), "Example note");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve this version?" });
    expect(dialog.textContent).toContain("tags the version high impact");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain("Example approval recorded."),
    );
    expect(sent).toEqual([{ decision: "approve", note: "Example note", high_impact: "on" }]);
  });

  it("returns and rejects only with a note, a candidate's rejection only with its reason", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<WriteAction<WriteResult>>(async (_state, formData) => {
      sent.push(sentOf(formData));
      return done("Example decided.");
    });
    const user = userEvent.setup();
    render(
      <DecidePanel
        action={action}
        view={{
          ...VIEW,
          candidateTask: true,
          canApprove: false,
          approveBlocked: "Example blocked",
        }}
        approvals={null}
      />,
    );
    expect(screen.getByText("Example blocked")).toBeDefined();
    const returnButton = screen.getByRole("button", { name: "Return" });
    expect(returnButton).toHaveProperty("disabled", true);
    const notes = screen.getAllByLabelText(/^Note/);
    await user.type(notes[0] as HTMLElement, "Example rework");
    expect(returnButton).toHaveProperty("disabled", false);
    await user.click(returnButton);
    await user.click(
      within(
        await screen.findByRole("dialog", { name: "Return the version for rework?" }),
      ).getByRole("button", { name: "Return" }),
    );
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    // The answer re-renders the panel; the next steps wait for it rather than racing it.
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Return the version for rework?" })).toBeNull(),
    );
    const reject = screen.getByRole("button", { name: "Reject" });
    await user.type(notes[1] as HTMLElement, "Example why");
    expect(reject).toHaveProperty("disabled", true);
    await user.selectOptions(screen.getByLabelText(/^Why the candidate is rejected/), "duplicate");
    await user.click(reject);
    const dialog = await screen.findByRole("dialog", { name: "Reject this task?" });
    expect(dialog.textContent).toContain("rejects the candidate");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
    expect(sent).toEqual([
      { decision: "return", note: "Example rework" },
      { decision: "reject", note: "Example why", reason: "duplicate" },
    ]);
  });

  it("cancels a dialog without sending, and says when the task is decided", async () => {
    const action = vi.fn<WriteAction<WriteResult>>();
    const user = userEvent.setup();
    const { rerender } = render(<DecidePanel action={action} view={VIEW} approvals={null} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(action).not.toHaveBeenCalled();
    rerender(<DecidePanel action={action} view={null} approvals={null} />);
    expect(screen.getByText("The task is decided: nothing more is decided here.")).toBeDefined();
  });

  it("says why each step that moves the version waits, and offers none of them", async () => {
    const waits = "Example: the web.publish_actions flag is off.";
    const { container } = render(
      <DecidePanel
        action={vi.fn<WriteAction<WriteResult>>()}
        view={{
          ...VIEW,
          canApprove: false,
          approveBlocked: waits,
          canReturn: false,
          returnBlocked: waits,
          canReject: false,
          rejectBlocked: waits,
        }}
        approvals={null}
      />,
    );
    for (const slot of ["approve-blocked", "return-blocked", "reject-blocked"]) {
      expect(container.querySelector(`[data-slot='${slot}']`)?.textContent).toBe(waits);
    }
    expect(screen.queryByRole("button")).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("keeps the high-impact tag once set, and offers no return before drafting", () => {
    render(
      <DecidePanel
        action={vi.fn<WriteAction<WriteResult>>()}
        view={{ ...VIEW, highImpact: true, canReturn: false }}
        approvals={null}
      />,
    );
    const box = screen.getByRole("checkbox", { name: /Mark it high impact/ });
    expect(box.getAttribute("data-state")).toBe("checked");
    expect(box).toHaveProperty("disabled", true);
    expect(screen.queryByRole("button", { name: "Return" })).toBeNull();
  });
});
