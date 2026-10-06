import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { dryRunReportFromDto } from "@/entities/applicability/mappers";
import { RUN_VERSION_ID, dryRunOutDto } from "@/test/engine-admin-fixture";
import { ontologyFixture } from "@/test/ontology-fixture";
import { initialValues } from "../model/form";
import { dryRunView } from "../model/report";
import { DryRunForm, type DryRunAction } from "./dry-run-form";

const REPORT = dryRunView(dryRunReportFromDto(dryRunOutDto()), ontologyFixture());

describe("DryRunForm", () => {
  it("runs a version with its scope and shows the counts, the attributes and the samples", async () => {
    const sent: Record<string, string>[] = [];
    const action = vi.fn<DryRunAction>(async (_state, formData) => {
      const values = Object.fromEntries([...formData.entries()].map(([k, v]) => [k, String(v)]));
      sent.push(values);
      return {
        status: "ok",
        value: { values: initialValues(RUN_VERSION_ID), report: REPORT },
        message: "The dry run finished; nothing was stored.",
      };
    });
    const { container } = render(
      <DryRunForm action={action} initial={initialValues(RUN_VERSION_ID)} />,
    );
    expect(await runAxe(container)).toHaveNoViolations();
    expect((screen.getByLabelText(/^Rule version id/) as HTMLInputElement).value).toBe(
      RUN_VERSION_ID,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Tenant id/), "example-tenant");
    await user.clear(screen.getByLabelText(/^Sample decisions/));
    await user.type(screen.getByLabelText(/^Sample decisions/), "5");
    await user.click(screen.getByRole("button", { name: "Run the dry run" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe(
        "The dry run finished; nothing was stored.",
      ),
    );
    expect(sent).toEqual([
      {
        subject: "version",
        rule_version_id: RUN_VERSION_ID,
        specification: "",
        "scope.level": "",
        "scope.tenant_id": "example-tenant",
        "scope.sample_size": "5",
      },
    ]);
    const report = container.querySelector("[data-slot='dry-run-report']") as HTMLElement;
    expect(report.textContent).toContain("example_rule (Draft)");
    expect(container.querySelector("[data-count='applies']")?.textContent).toContain("1");
    expect(container.querySelector("[data-attribute='example_kind']")?.textContent).toContain(
      "example_kind",
    );
    expect(container.querySelector("[data-slot='dry-run-samples']")?.textContent).toContain(
      "Decided by example_kind",
    );
    expect(await runAxe(report)).toHaveNoViolations();
  });

  it("asks for a specification and its level, keeps the values and shows each field's refusal", async () => {
    const action = vi.fn<DryRunAction>(async () => ({
      status: "error",
      fieldErrors: {
        specification: ["Example specification refused"],
        "scope.level": ["Example level refused"],
      },
    }));
    render(<DryRunForm action={action} initial={initialValues(null)} />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/^What to run/), "specification");
    expect(screen.queryByLabelText(/^Rule version id/)).toBeNull();
    await user.click(screen.getByLabelText(/^Specification/));
    await user.paste('{"attribute": "example_kind"}');
    await user.click(screen.getByRole("button", { name: "Run the dry run" }));
    await waitFor(() => expect(screen.getByText("Example specification refused")).toBeDefined());
    expect(screen.getByText("Example level refused")).toBeDefined();
    expect((screen.getByLabelText(/^Specification/) as HTMLTextAreaElement).value).toBe(
      '{"attribute": "example_kind"}',
    );
  });

  it("shows the engine's refusal with the way to narrow the scope", async () => {
    const action = vi.fn<DryRunAction>(async () => ({
      status: "error",
      problem: {
        type: "urn:compliancewatch:problem:applicability-dry-run-too-large",
        title: "Example scope too large",
        correlationId: "req-example-6",
      },
      formErrors: ["Name a tenant to narrow the scope to its businesses."],
    }));
    render(<DryRunForm action={action} initial={initialValues(RUN_VERSION_ID)} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Run the dry run" }));
    await waitFor(() => expect(screen.getByText("Example scope too large")).toBeDefined());
    expect(screen.getByText("req-example-6")).toBeDefined();
    expect(screen.getByText("Name a tenant to narrow the scope to its businesses.")).toBeDefined();
  });
});
