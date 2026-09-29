import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { runAxe } from "../test/axe";
import { DataTable, type DataTableColumn } from "./data-table";

interface Row {
  id: string;
  name: string;
  amount: number;
}

const columns: DataTableColumn<Row>[] = [
  { id: "name", header: "Name", cell: (row) => row.name, sortable: true },
  { id: "amount", header: "Amount", cell: (row) => row.amount, sortable: true, align: "right" },
  { id: "id", header: "Id", cell: (row) => row.id },
];

const rows: Row[] = [
  { id: "1", name: "Example one", amount: 10 },
  { id: "2", name: "Example two", amount: 20 },
];

describe("DataTable", () => {
  it("renders rows, reports sort changes through buttons with aria-sort, and pages with buttons", async () => {
    const onSortChange = vi.fn();
    const onNext = vi.fn();
    const { container } = render(
      <DataTable
        caption="Example rows"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        sort={{ id: "name", dir: "asc" }}
        onSortChange={onSortChange}
        pagination={{ mode: "cursor", hasNext: true, hasPrev: false, onNext, label: "Showing 2" }}
        filters={<input aria-label="Filter" />}
      />,
    );
    expect(screen.getByRole("table", { name: "Example rows" })).toBeDefined();
    const [name, amount, id] = screen.getAllByRole("columnheader");
    expect(name?.getAttribute("aria-sort")).toBe("ascending");
    expect(amount?.getAttribute("aria-sort")).toBe("none");
    expect(id?.getAttribute("aria-sort")).toBeNull();
    expect(amount?.className).toContain("text-right");
    expect(screen.getAllByRole("row")).toHaveLength(3);
    await userEvent.click(within(name as HTMLElement).getByRole("button"));
    expect(onSortChange).toHaveBeenCalledWith({ id: "name", dir: "desc" });
    await userEvent.click(within(amount as HTMLElement).getByRole("button"));
    expect(onSortChange).toHaveBeenCalledWith({ id: "amount", dir: "asc" });
    const prev = screen.getByRole("button", { name: "Previous page" }) as HTMLButtonElement;
    expect(prev.disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("navigation", { name: "Pagination" }).textContent).toContain(
      "Showing 2",
    );
    expect(screen.getByLabelText("Filter")).toBeDefined();
    expect(
      container.querySelector('[data-slot="data-table-pagination"]')?.getAttribute("data-mode"),
    ).toBe("cursor");
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("renders sort and paging as links for server-rendered pages", () => {
    render(
      <DataTable
        caption="Example rows"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id}
        sort={{ id: "amount", dir: "desc" }}
        sortHref={(sort) => `/list?sort=${sort.id}:${sort.dir}`}
        pagination={{
          mode: "offset",
          hasNext: true,
          hasPrev: true,
          nextHref: "/list?page=3",
          prevHref: "/list?page=1",
          label: "Page 2",
        }}
      />,
    );
    const [name, amount] = screen.getAllByRole("columnheader");
    expect(amount?.getAttribute("aria-sort")).toBe("descending");
    expect(
      within(name as HTMLElement)
        .getByRole("link")
        .getAttribute("href"),
    ).toBe("/list?sort=name:asc");
    expect(
      within(amount as HTMLElement)
        .getByRole("link")
        .getAttribute("href"),
    ).toBe("/list?sort=amount:asc");
    expect(screen.getByRole("link", { name: "Next page" }).getAttribute("href")).toBe(
      "/list?page=3",
    );
    expect(screen.getByRole("link", { name: "Previous page" }).getAttribute("href")).toBe(
      "/list?page=1",
    );
  });

  it("shows the empty slot across every column and plain headers without sorting", () => {
    render(
      <DataTable
        caption="Empty"
        columns={columns}
        rows={[]}
        rowKey={(row) => row.id}
        empty="No rows because nothing was recorded."
      />,
    );
    const cell = screen.getByText("No rows because nothing was recorded.");
    expect(cell.getAttribute("colspan")).toBe("3");
    expect(screen.getAllByRole("columnheader")[0]?.getAttribute("aria-sort")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("falls back to a default empty message and a disabled next link when there is no next page", () => {
    render(
      <DataTable
        caption="Empty"
        columns={columns}
        rows={[]}
        rowKey={(row) => row.id}
        pagination={{
          mode: "offset",
          hasNext: false,
          hasPrev: false,
          nextHref: "/x",
          prevHref: "/y",
        }}
      />,
    );
    expect(screen.getByText("Nothing to show.")).toBeDefined();
    expect((screen.getByRole("button", { name: "Next page" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(
      (screen.getByRole("button", { name: "Previous page" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
