"use server";

import { requireScreenSession } from "@/server/dal";
import { toActionState } from "@/server/result";
import { screenById } from "@/shared/config/screens";
import type { ActionState } from "@/shared/lib/action-state";
import { searchGateway } from "./gateway";
import { searchResults } from "./model/hits";
import { parseSearchForm } from "./model/search-form";
import type { SearchResults } from "./ui/search-shared";

/**
 * Searches the clauses: the tool's gate again, the form's shape, then the rulebook. The words
 * are posted and answered here, so they never reach an address, the browser history or a log of
 * the page's path.
 */
export async function searchClauses(
  _state: ActionState<SearchResults>,
  formData: FormData,
): Promise<ActionState<SearchResults>> {
  await requireScreenSession(screenById("admin.rulebook.search"));
  const parsed = parseSearchForm(formData);
  if (!parsed.ok) return { status: "error", fieldErrors: parsed.fieldErrors };
  const hits = await searchGateway().search(parsed.query);
  if (!hits.ok) return toActionState<SearchResults>({ ok: false, error: hits.error });
  return { status: "ok", value: searchResults(parsed.query.text, hits.value) };
}
