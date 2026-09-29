import type { BusinessPage } from "@/entities/business/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";

/**
 * The businesses list: a business tenant's own businesses, or a CA firm's clients, a page at a
 * time from `GET /v1/businesses` (by name, with an opaque cursor for the next page). The search
 * term matches a name, a PAN or a GSTIN, so it travels in a POST body (the search form's server
 * action), never in the URL.
 */
export const DIRECTORY_FIELDS = { q: "q", cursor: "cursor", page: "page" } as const;

export type DirectoryFields = typeof DIRECTORY_FIELDS;

/** Rows per page; the service allows up to 100. */
export const DIRECTORY_PAGE_SIZE = 20;

/** The service's limits on the search term. */
export const SEARCH_MAX_LENGTH = 100;

export interface DirectoryRow {
  id: string;
  name: string;
  pan: string;
  gstins: string;
  updatedAt: string;
  href: string;
}

export interface DirectoryPage {
  /** The search term the page was read with; "" for the whole list. */
  q: string;
  /** One-based. */
  page: number;
  rows: readonly DirectoryRow[];
  nextCursor: string | null;
}

export function directoryPage(
  page: BusinessPage,
  q: string,
  pageNumber: number,
  hrefOf: (businessId: string) => string,
): DirectoryPage {
  return {
    q,
    page: pageNumber,
    rows: page.items.map((item) => ({
      id: item.id,
      name: item.name,
      pan: item.pan,
      gstins: item.gstins.length === 0 ? t("directory.noGstin") : item.gstins.join(", "),
      updatedAt: formatDateTime(item.updatedAt),
      href: hrefOf(item.id),
    })),
    nextCursor: page.nextCursor,
  };
}

export type DirectoryQuery =
  { ok: true; q: string; cursor: string | undefined; page: number } | { ok: false; error: string };

/** The search form's or the pager's fields: a trimmed term, the cursor and the page number. */
export function readDirectoryQuery(formData: FormData): DirectoryQuery {
  const read = (field: string) => {
    const value = formData.get(field);
    return typeof value === "string" ? value.trim() : "";
  };
  const q = read(DIRECTORY_FIELDS.q);
  if (q.length > SEARCH_MAX_LENGTH) {
    return { ok: false, error: t("directory.error.tooLong", { max: SEARCH_MAX_LENGTH }) };
  }
  const cursor = read(DIRECTORY_FIELDS.cursor);
  const page = Number(read(DIRECTORY_FIELDS.page));
  return {
    ok: true,
    q,
    cursor: cursor === "" ? undefined : cursor,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}
