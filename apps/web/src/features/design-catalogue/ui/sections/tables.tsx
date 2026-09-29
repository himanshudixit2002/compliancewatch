import { useState } from "react";
import {
  DataTable,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { DataTableColumn, DataTableSort } from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import type { ExampleRow } from "../fixtures";
import { CatalogueSection, Example } from "./section";

const COLUMNS: readonly DataTableColumn<ExampleRow>[] = [
  { id: "name", header: "Name", cell: (row) => row.name, sortable: true },
  { id: "due", header: "Due", cell: (row) => row.due, sortable: true },
  { id: "amount", header: "Amount", cell: (row) => row.amount, align: "right" },
  {
    id: "state",
    header: "State",
    cell: (row) => (
      <StatusChip status={row.state} tone={row.state === "done" ? "success" : "neutral"} />
    ),
  },
];

function sortRows(rows: readonly ExampleRow[], sort: DataTableSort): ExampleRow[] {
  const key = sort.id === "due" ? "due" : "name";
  const sorted = [...rows].sort((a, b) => a[key].localeCompare(b[key]));
  return sort.dir === "asc" ? sorted : sorted.reverse();
}

export function TablesSection() {
  const [sort, setSort] = useState<DataTableSort>({ id: "name", dir: "asc" });
  const [page, setPage] = useState(1);
  return (
    <CatalogueSection
      id="tables"
      title="Tables"
      description="The primitive table, and DataTable with sorting and paging reported through callbacks."
    >
      <Example label="Table">
        <Table>
          <TableCaption>Example items</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Due</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {FIXTURES.rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell>{row.name}</TableCell>
                <TableCell>{row.due}</TableCell>
                <TableCell className="text-right">{row.amount}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Example>
      <Example label="Data table">
        <DataTable
          className="w-full"
          caption="Example items with sorting and paging"
          columns={COLUMNS}
          rows={sortRows(FIXTURES.rows, sort)}
          rowKey={(row) => row.id}
          sort={sort}
          onSortChange={setSort}
          pagination={{
            mode: "offset",
            hasPrev: page > 1,
            hasNext: page < 3,
            onPrev: () => setPage((current) => current - 1),
            onNext: () => setPage((current) => current + 1),
            label: `Page ${page} of 3`,
          }}
        />
      </Example>
      <Example label="Empty data table">
        <DataTable
          className="w-full"
          caption="Example items, none yet"
          columns={COLUMNS}
          rows={[]}
          rowKey={(row) => row.id}
          empty="Nothing has been recorded for this example yet."
        />
      </Example>
    </CatalogueSection>
  );
}
