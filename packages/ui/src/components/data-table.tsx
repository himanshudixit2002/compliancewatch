import type { ReactNode } from "react";
import { ArrowDownIcon, ArrowUpIcon, ArrowUpDownIcon } from "lucide-react";
import { cn } from "../lib/cn";
import { Button } from "./button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./table";

export interface DataTableColumn<Row> {
  id: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  sortable?: boolean;
  align?: "left" | "right";
  className?: string;
}

export interface DataTableSort {
  id: string;
  dir: "asc" | "desc";
}

export interface DataTablePagination {
  /** Cursor paging reports only whether a next page exists; offset paging can also label pages. */
  mode: "cursor" | "offset";
  hasNext: boolean;
  hasPrev: boolean;
  /** Client-side callbacks... */
  onNext?: () => void;
  onPrev?: () => void;
  /** ...or links for server-rendered pages where the state lives in the URL. */
  nextHref?: string;
  prevHref?: string;
  /** For example "Page 2" or "Showing 20 of 63". */
  label?: ReactNode;
}

export interface DataTableProps<Row> {
  caption: ReactNode;
  columns: readonly DataTableColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  sort?: DataTableSort;
  /** Client-side sorting callback... */
  onSortChange?: (sort: DataTableSort) => void;
  /** ...or a link builder for server-rendered pages. */
  sortHref?: (sort: DataTableSort) => string;
  pagination?: DataTablePagination;
  /** Filter controls rendered above the table. */
  filters?: ReactNode;
  /** Shown instead of the body when there are no rows; say why the list is empty. */
  empty?: ReactNode;
  className?: string;
}

function nextSort(column: string, current: DataTableSort | undefined): DataTableSort {
  const dir = current?.id === column && current.dir === "asc" ? "desc" : "asc";
  return { id: column, dir };
}

/**
 * A table over rows the page already has: sorting and paging are reported through callbacks
 * or rendered as links, never fetched here.
 */
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  sortHref,
  pagination,
  filters,
  empty,
  className,
}: DataTableProps<Row>) {
  const sortIcon = (id: string) =>
    sort?.id !== id ? (
      <ArrowUpDownIcon aria-hidden="true" className="size-3.5 text-fg-muted" />
    ) : sort.dir === "asc" ? (
      <ArrowUpIcon aria-hidden="true" className="size-3.5" />
    ) : (
      <ArrowDownIcon aria-hidden="true" className="size-3.5" />
    );

  return (
    <div data-slot="data-table" className={cn("flex flex-col gap-3", className)}>
      {filters ? (
        <div data-slot="data-table-filters" className="flex flex-wrap gap-2">
          {filters}
        </div>
      ) : null}
      <Table>
        <TableCaption>{caption}</TableCaption>
        <TableHeader>
          <TableRow>
            {columns.map((column) => {
              const sortable = column.sortable && (onSortChange || sortHref);
              const ariaSort =
                sort?.id === column.id
                  ? sort.dir === "asc"
                    ? "ascending"
                    : "descending"
                  : sortable
                    ? "none"
                    : undefined;
              const target = nextSort(column.id, sort);
              return (
                <TableHead
                  key={column.id}
                  aria-sort={ariaSort}
                  className={cn(column.align === "right" && "text-right", column.className)}
                >
                  {sortable ? (
                    sortHref ? (
                      <a
                        href={sortHref(target)}
                        className="inline-flex items-center gap-1 rounded-sm hover:underline"
                      >
                        {column.header}
                        {sortIcon(column.id)}
                      </a>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onSortChange?.(target)}
                        className="inline-flex items-center gap-1 rounded-sm hover:underline"
                      >
                        {column.header}
                        {sortIcon(column.id)}
                      </button>
                    )
                  ) : (
                    column.header
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="p-4 text-center whitespace-normal text-fg-muted"
              >
                {empty ?? "Nothing to show."}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((column) => (
                  <TableCell
                    key={column.id}
                    className={cn(column.align === "right" && "text-right", column.className)}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {pagination ? (
        <nav
          aria-label="Pagination"
          data-slot="data-table-pagination"
          data-mode={pagination.mode}
          className="flex items-center justify-between gap-2 text-sm text-fg-muted"
        >
          <span>{pagination.label}</span>
          <div className="flex gap-2">
            {pagination.prevHref && pagination.hasPrev ? (
              <Button asChild variant="secondary" size="sm">
                <a href={pagination.prevHref} aria-label="Previous page">
                  Previous
                </a>
              </Button>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                aria-label="Previous page"
                disabled={!pagination.hasPrev}
                onClick={pagination.onPrev}
              >
                Previous
              </Button>
            )}
            {pagination.nextHref && pagination.hasNext ? (
              <Button asChild variant="secondary" size="sm">
                <a href={pagination.nextHref} aria-label="Next page">
                  Next
                </a>
              </Button>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                aria-label="Next page"
                disabled={!pagination.hasNext}
                onClick={pagination.onNext}
              >
                Next
              </Button>
            )}
          </div>
        </nav>
      ) : null}
    </div>
  );
}
