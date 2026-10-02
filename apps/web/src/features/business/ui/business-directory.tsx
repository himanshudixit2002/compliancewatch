"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useEffect, useRef } from "react";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { ActionState } from "@/shared/lib/action-state";

/** One page of the list (the business model's DirectoryPage, structurally). */
export interface DirectoryPageData {
  q: string;
  page: number;
  rows: readonly {
    id: string;
    name: string;
    pan: string;
    gstins: string;
    updatedAt: string;
    href: string;
  }[];
  nextCursor: string | null;
}

export type DirectoryAction = (
  state: ActionState<DirectoryPageData>,
  formData: FormData,
) => Promise<ActionState<DirectoryPageData>>;

export interface BusinessDirectoryProps {
  title: string;
  /** "clients" for a CA firm: the copy speaks of clients rather than businesses. */
  audience: "owner" | "clients";
  initial: DirectoryPageData;
  action: DirectoryAction;
  fields: { q: string; cursor: string; page: string };
  /** The business step, or null for a role that does not add businesses. */
  addHref: string | null;
  /** The consent step, where a new tenant starts. */
  startHref: string | null;
}

interface Attempt {
  state: ActionState<DirectoryPageData>;
  shown: DirectoryPageData;
  count: number;
}

/**
 * The tenant's businesses, or a CA firm's clients, by name, a page at a time. Searching and
 * paging post to a server action (the term can be a PAN or a GSTIN, which stays out of URLs),
 * and the table shows the last page read; a failed read keeps it and shows the problem. The
 * status line says what is shown and takes focus after each search or page.
 */
export function BusinessDirectory({
  title,
  audience,
  initial,
  action,
  fields,
  addHref,
  startHref,
}: BusinessDirectoryProps) {
  const [attempt, formAction, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const state = await action(previous.state, formData);
      return {
        state,
        shown: state.status === "ok" && state.value !== undefined ? state.value : previous.shown,
        count: previous.count + 1,
      };
    },
    { state: { status: "ok", value: initial }, shown: initial, count: 0 },
  );
  const { state, shown } = attempt;
  const statusRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (attempt.count > 0) statusRef.current?.focus();
  }, [attempt]);

  const count = shown.rows.length;
  const status =
    shown.q === ""
      ? t(`directory.${audience}.showing`, { count, page: shown.page })
      : t("directory.matching", { count, q: shown.q, page: shown.page });
  const busy = pending || undefined;

  return (
    <div data-slot="business-directory" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t(`directory.${audience}.intro`)}
        actions={
          addHref === null ? undefined : (
            <Button asChild>
              <Link href={addHref as Route}>{t(`directory.${audience}.add`)}</Link>
            </Button>
          )
        }
      />
      <form action={formAction} role="search" className="flex flex-wrap items-end gap-2">
        <input type="hidden" name={fields.page} value="1" />
        <Field
          id="directory-q"
          label={t("directory.searchLabel")}
          description={t("directory.searchHelp")}
          className="w-full max-w-md"
        >
          <Input name={fields.q} defaultValue={shown.q} key={`${attempt.count}-${shown.q}`} />
        </Field>
        <Button type="submit" disabled={pending} aria-busy={busy}>
          {t("directory.search")}
        </Button>
      </form>
      {state.status === "error" ? (
        <ErrorState
          title={state.problem?.title ?? t("directory.failed")}
          detail={state.problem?.detail ?? state.formErrors?.join(" ")}
          correlationId={state.problem?.correlationId || undefined}
        />
      ) : null}
      <p
        ref={statusRef}
        tabIndex={-1}
        role="status"
        data-slot="directory-status"
        className="text-sm text-fg outline-none"
      >
        {status}
      </p>
      {count === 0 ? (
        shown.q === "" ? (
          <EmptyState
            title={t(`directory.${audience}.emptyTitle`)}
            body={t(`directory.${audience}.emptyBody`)}
            action={
              startHref === null ? undefined : (
                <Button asChild variant="secondary">
                  <Link href={startHref as Route}>{t("directory.start")}</Link>
                </Button>
              )
            }
          />
        ) : (
          <EmptyState
            title={t("directory.noMatchTitle")}
            body={t("directory.noMatchBody", { q: shown.q })}
          />
        )
      ) : (
        <Table data-slot="directory-table" scrollLabel={t(`directory.${audience}.caption`)}>
          <TableCaption>{t(`directory.${audience}.caption`)}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("business.name")}</TableHead>
              <TableHead>{t("prefill.pan")}</TableHead>
              <TableHead>{t("business.registrations")}</TableHead>
              <TableHead>{t("business.updatedAt")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.rows.map((row) => (
              <TableRow key={row.id} data-business-id={row.id}>
                <TableCell>
                  <Link href={row.href as Route} className="font-medium text-primary underline">
                    {row.name}
                  </Link>
                </TableCell>
                <TableCell>{row.pan}</TableCell>
                <TableCell>{row.gstins}</TableCell>
                <TableCell>{row.updatedAt}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {shown.page > 1 || shown.nextCursor !== null ? (
        <nav aria-label={t("directory.pages")} className="flex flex-wrap gap-2">
          {shown.page > 1 ? (
            <form action={formAction}>
              <input type="hidden" name={fields.q} value={shown.q} />
              <input type="hidden" name={fields.page} value="1" />
              <Button type="submit" variant="secondary" size="sm" disabled={pending}>
                {t("directory.firstPage")}
              </Button>
            </form>
          ) : null}
          {shown.nextCursor === null ? null : (
            <form action={formAction}>
              <input type="hidden" name={fields.q} value={shown.q} />
              <input type="hidden" name={fields.cursor} value={shown.nextCursor} />
              <input type="hidden" name={fields.page} value={String(shown.page + 1)} />
              <Button type="submit" variant="secondary" size="sm" disabled={pending}>
                {t("directory.nextPage")}
              </Button>
            </form>
          )}
        </nav>
      ) : null}
    </div>
  );
}
