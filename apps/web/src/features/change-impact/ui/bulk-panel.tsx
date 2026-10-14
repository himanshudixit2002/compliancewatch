"use client";

import { startTransition, useActionState, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Banner,
  Button,
  ConfirmDialog,
  ErrorState,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { idleAction, type ActionState } from "@/shared/lib/action-state";
import { IDEMPOTENCY_KEY_FIELD } from "@/shared/lib/idempotency";
import { BULK_FIELDS, type BulkSummary, type BulkTarget } from "./bulk-shared";

export type BulkAction = (
  state: ActionState<BulkSummary>,
  formData: FormData,
) => Promise<ActionState<BulkSummary>>;

export interface BulkPanelProps {
  /** The send action, bound to the change. */
  action: BulkAction;
  /** The affected businesses the card names. */
  targets: readonly BulkTarget[];
  /** More businesses are affected than one card names, or the page could not walk them all. */
  cut: boolean;
  /** The hidden Idempotency-Key input the page minted for this render. */
  idempotencyInput: ReactNode;
}

/** A request this panel sent: its key and the businesses it named, in the order sent. */
interface SentRequest {
  key: string;
  businesses: readonly string[];
}

interface Attempt {
  last: ActionState<BulkSummary>;
  /** The request whose answer never arrived, kept whole (key included) for "Try again". */
  lost: FormData | null;
  count: number;
  /**
   * The last request sent from this panel, so the same businesses sent again carry the same key
   * however often the page minted a new one since: a server action whose request refreshed the
   * session cookie re-renders the page (Next refreshes the tree when cookies change), and the
   * hidden input then holds a key the service has never seen.
   */
  sent: SentRequest | null;
}

const START: Attempt = { last: idleAction(), lost: null, count: 0, sent: null };

function sentRequestOf(formData: FormData): SentRequest | null {
  const key = formData.get(IDEMPOTENCY_KEY_FIELD);
  if (typeof key !== "string" || key === "") return null;
  return { key, businesses: formData.getAll(BULK_FIELDS.businessId).map(String) };
}

function sameBusinesses(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}

/**
 * The form's data with the key this panel already sent for these businesses, in this order,
 * else with the page's key as the form holds it: the same request keeps its key, a different
 * one (another list of businesses) takes a new one.
 */
function withSentKey(formData: FormData, sent: SentRequest | null): FormData {
  if (sent === null) return formData;
  const businesses = formData.getAll(BULK_FIELDS.businessId).map(String);
  if (sameBusinesses(sent.businesses, businesses)) formData.set(IDEMPOTENCY_KEY_FIELD, sent.key);
  return formData;
}

function isFrameworkError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("digest" in error)) return false;
  return String((error as { digest: unknown }).digest).startsWith("NEXT_");
}

/**
 * One change card to the affected clients' own people (an owner or staff who follows the
 * client; the firm's own people hear in their daily digest). The form carries the businesses and
 * the key the page minted, so sending again from the same page, or "Try again" after an answer
 * that never arrived, is the same request: the service sends nothing twice and answers with its
 * first answer, which the panel says in words. The panel keeps the key it sent for these
 * businesses (`withSentKey`), so the request stays the same even once the page re-rendered and
 * minted another key behind the form. The outcome lists what became of each business.
 */
export function BulkPanel({ action, targets, cut, idempotencyInput }: BulkPanelProps) {
  const formRef = useRef<HTMLFormElement>(null);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const [confirming, setConfirming] = useState(false);
  const [attempt, dispatch, pending] = useActionState(
    async (previous: Attempt, formData: FormData): Promise<Attempt> => {
      const sent = sentRequestOf(formData) ?? previous.sent;
      try {
        const last = await action(idleAction(), formData);
        return { last, lost: null, count: previous.count + 1, sent };
      } catch (error) {
        if (isFrameworkError(error)) throw error;
        return { last: previous.last, lost: formData, count: previous.count + 1, sent };
      }
    },
    START,
  );
  useEffect(() => {
    if (attempt.count > 0) outcomeRef.current?.focus();
  }, [attempt]);
  const labels = new Map(targets.map((target) => [target.businessId, target.label]));
  const send = (formData: FormData) => startTransition(() => dispatch(formData));
  const { last, lost, sent } = attempt;
  const formErrors = last.status === "error" ? (last.formErrors ?? []) : [];
  return (
    <section aria-labelledby="bulk-heading" data-slot="bulk-panel" className="flex flex-col gap-3">
      <h2 id="bulk-heading" className="text-lg font-semibold text-fg">
        {t("changeImpact.bulk.heading")}
      </h2>
      <p className="max-w-prose text-sm text-fg-muted">{t("changeImpact.bulk.intro")}</p>
      {targets.length === 0 ? (
        <p className="text-sm text-fg-muted" data-slot="bulk-nobody">
          {t("changeImpact.bulk.none")}
        </p>
      ) : (
        <form
          ref={formRef}
          aria-label={t("changeImpact.bulk.formLabel")}
          className="flex flex-col gap-3"
        >
          {idempotencyInput}
          {targets.map((target) => (
            <input
              key={target.businessId}
              type="hidden"
              name={BULK_FIELDS.businessId}
              value={target.businessId}
            />
          ))}
          {cut ? (
            <Banner tone="warning" title={t("changeImpact.bulk.cutTitle")}>
              {t("changeImpact.bulk.cut", { count: targets.length })}
            </Banner>
          ) : null}
          <div>
            <Button
              type="button"
              disabled={pending}
              aria-busy={pending || undefined}
              onClick={() => setConfirming(true)}
            >
              {targets.length === 1
                ? t("changeImpact.bulk.sendOne")
                : t("changeImpact.bulk.sendMany", { count: targets.length })}
            </Button>
          </div>
        </form>
      )}
      <div
        ref={outcomeRef}
        tabIndex={-1}
        data-slot="bulk-outcome"
        data-replayed={last.status === "ok" && last.value?.replayed ? "true" : undefined}
        className="flex flex-col gap-3 outline-none"
      >
        {lost !== null ? (
          <Banner
            tone="warning"
            title={t("changeImpact.bulk.lostTitle")}
            action={
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={pending}
                aria-busy={pending || undefined}
                onClick={() => send(lost)}
              >
                {t("changeImpact.bulk.retry")}
              </Button>
            }
          >
            {t("changeImpact.bulk.lostBody")}
          </Banner>
        ) : last.status === "ok" && last.value !== undefined ? (
          <>
            <p role="status" className="text-sm font-medium text-fg" data-slot="bulk-done">
              {last.value.message}
            </p>
            <Table scrollLabel={t("changeImpact.bulk.resultRegion")} data-slot="bulk-result">
              <TableCaption className="text-left text-sm text-fg-muted">
                {t("changeImpact.bulk.resultCaption")}
              </TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">{t("changeImpact.bulk.column.business")}</TableHead>
                  <TableHead scope="col">{t("changeImpact.bulk.column.outcome")}</TableHead>
                  <TableHead scope="col">{t("changeImpact.bulk.column.people")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {last.value.businesses.map((entry) => (
                  <TableRow
                    key={entry.businessId}
                    data-business={entry.businessId}
                    data-outcome={entry.outcome}
                  >
                    <TableCell className="align-top whitespace-normal">
                      {labels.get(entry.businessId) ?? entry.businessId}
                    </TableCell>
                    <TableCell className="align-top">{entry.outcomeLabel}</TableCell>
                    <TableCell className="align-top whitespace-normal text-fg-muted">
                      {entry.people}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        ) : last.status === "error" ? (
          <>
            {last.problem === undefined ? null : (
              <ErrorState
                title={last.problem.title}
                detail={last.problem.detail}
                correlationId={last.problem.correlationId || undefined}
              />
            )}
            {formErrors.map((message, index) => (
              <p key={index} role="alert" className="text-sm text-danger">
                {message}
              </p>
            ))}
          </>
        ) : null}
      </div>
      {confirming ? (
        <ConfirmDialog
          open
          onOpenChange={(next) => {
            if (!next) setConfirming(false);
          }}
          title={t("changeImpact.bulk.dialogTitle")}
          description={t("changeImpact.bulk.dialogBody", { count: targets.length })}
          confirmLabel={t("changeImpact.bulk.confirm")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={() => {
            setConfirming(false);
            if (formRef.current !== null) send(withSentKey(new FormData(formRef.current), sent));
          }}
        />
      ) : null}
    </section>
  );
}
