import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { runAxe } from "../test/axe";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "./table";

describe("Table", () => {
  it("renders a captioned table with column headers scoped by default", async () => {
    const { container } = render(
      <Table>
        <TableCaption>Example rows</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead scope="colgroup">Value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow data-state="selected">
            <TableCell>Example</TableCell>
            <TableCell>1</TableCell>
          </TableRow>
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell>Total</TableCell>
            <TableCell>1</TableCell>
          </TableRow>
        </TableFooter>
      </Table>,
    );
    const table = screen.getByRole("table", { name: "Example rows" });
    expect(table.dataset.slot).toBe("table");
    const [name, value] = screen.getAllByRole("columnheader");
    expect(name?.getAttribute("scope")).toBe("col");
    expect(value?.getAttribute("scope")).toBe("colgroup");
    expect(screen.getByText("Example").closest("tr")?.dataset.state).toBe("selected");
    expect(container.querySelector('[data-slot="table-footer"]')).not.toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
