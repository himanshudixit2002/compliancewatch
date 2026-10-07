"use client";

import type { Route } from "next";
import Link from "next/link";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { RuleVersionStatusChip } from "@/shared/ui/rule-version-status";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import { CLAIM_FIELD, type WriteResult } from "./form-shared";
import { PersonName, WriteResultView } from "./write-result";

/** A queue row as the list shows it (model/queue.ts builds it on the server). */
export interface QueueListRow {
  taskId: string;
  href: string;
  kind: string;
  kindLabel: string;
  title: string;
  ruleLabel: string | null;
  suggested: boolean;
  versionStatus: string | null;
  approvals: string;
  highImpact: boolean;
  candidate: {
    outcome: string;
    unparseable: boolean;
    confidence: string;
    issues: string;
    needsReview: boolean;
  } | null;
  status: string;
  statusLabel: string;
  claimedBy: { userId: string; you: boolean } | null;
  claimedAt: string | null;
  mine: boolean;
  decision: {
    label: string;
    by: { userId: string; you: boolean } | null;
    at: string | null;
    note: string;
  } | null;
  claimable: boolean;
}

export interface QueueListProps {
  rows: readonly QueueListRow[];
  caption: string;
  /** The claim, for a session that may send it; null shows no claim button. */
  claim: WriteAction<WriteResult> | null;
}

const TONES = { open: "warning", claimed: "info", decided: "success" } as const;

/** Keys typed into a control are the control's: the shortcuts never take them. */
function inControl(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return target.closest("[role='dialog']") !== null;
}

/**
 * The queue's rows with their keyboard: the rows' title links are one stop in the tab order (a
 * roving tabindex, the current row's link takes the stop), j and k move to the next and previous
 * row, Enter opens the task (the link's own behaviour), c claims the current row's task when it
 * is open, and ? lists the shortcuts in a dialog. A key typed into a form control is the
 * control's, the shortcuts ignore modifier keys, and Tab always leaves the list as usual.
 */
export function QueueList({ rows, caption, claim }: QueueListProps) {
  const id = useId();
  const [active, setActive] = useState(0);
  const [help, setHelp] = useState(false);
  const links = useRef<(HTMLAnchorElement | null)[]>([]);
  const forms = useRef<(HTMLFormElement | null)[]>([]);
  const fallback: WriteAction<WriteResult> = async (state) => state;
  const { attempt, send, pending, outcomeRef } = useWriteAction(claim ?? fallback);
  const current = Math.min(active, Math.max(rows.length - 1, 0));

  const focusRow = (index: number) => {
    const target = Math.min(Math.max(index, 0), rows.length - 1);
    setActive(target);
    links.current[target]?.focus();
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (inControl(event.target)) return;
      if (event.key === "?") {
        event.preventDefault();
        setHelp(true);
        return;
      }
      if (rows.length === 0) return;
      const inList = links.current.some((link) => link === document.activeElement);
      if (event.key === "j") {
        event.preventDefault();
        focusRow(inList ? current + 1 : current);
      } else if (event.key === "k") {
        event.preventDefault();
        focusRow(inList ? current - 1 : current);
      } else if (event.key === "c" && claim !== null && rows[current]?.claimable === true) {
        event.preventDefault();
        forms.current[current]?.requestSubmit();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const onLinkKey = (event: ReactKeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (event.key === "Home") {
      event.preventDefault();
      focusRow(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusRow(rows.length - 1);
    } else if (index !== current) {
      setActive(index);
    }
  };

  return (
    <div className="flex flex-col gap-3" data-slot="queue-list">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p id={`${id}-hint`} className="text-sm text-fg-muted">
          {t("reviewQueue.keys.hint")}
        </p>
        <Button type="button" variant="secondary" size="sm" onClick={() => setHelp(true)}>
          {t("reviewQueue.keys.button")}
        </Button>
      </div>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="queue-claim-outcome"
        renderValue={(value) => <WriteResultView result={value} />}
      />
      <Table scrollLabel={t("reviewQueue.tableRegion")} data-slot="queue-table">
        <TableCaption className="text-left text-sm text-fg-muted">{caption}</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{t("reviewQueue.column.task")}</TableHead>
            <TableHead scope="col">{t("reviewQueue.column.version")}</TableHead>
            <TableHead scope="col">{t("reviewQueue.column.candidate")}</TableHead>
            <TableHead scope="col">{t("reviewQueue.column.claim")}</TableHead>
            <TableHead scope="col">{t("reviewQueue.column.status")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow
              key={row.taskId}
              data-task={row.taskId}
              data-status={row.status}
              data-kind={row.kind}
              data-mine={row.mine || undefined}
              data-current={index === current || undefined}
            >
              <TableCell className="align-top">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-fg-muted">{row.kindLabel}</span>
                  <Link
                    ref={(element) => {
                      links.current[index] = element;
                    }}
                    href={row.href as Route}
                    tabIndex={index === current ? 0 : -1}
                    aria-describedby={`${id}-hint`}
                    onFocus={() => setActive(index)}
                    onKeyDown={(event) => onLinkKey(event, index)}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                    data-slot="task-link"
                  >
                    {row.title}
                  </Link>
                  {row.ruleLabel === null ? null : (
                    <span className="font-mono text-xs text-fg-muted">
                      {row.suggested
                        ? t("reviewQueue.suggestedKey", { key: row.ruleLabel })
                        : row.ruleLabel}
                    </span>
                  )}
                </div>
              </TableCell>
              <TableCell className="align-top text-sm">
                <div className="flex flex-col items-start gap-1">
                  {row.versionStatus === null ? (
                    <span className="text-fg-muted">{t("reviewQueue.notDrafted")}</span>
                  ) : (
                    <RuleVersionStatusChip status={row.versionStatus} />
                  )}
                  <span>{row.approvals}</span>
                  {row.highImpact ? (
                    <Badge tone="warning">{t("reviewQueue.highImpact")}</Badge>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="align-top text-sm">
                {row.candidate === null ? (
                  <span className="text-fg-muted">{t("reviewQueue.noCandidate")}</span>
                ) : (
                  <div className="flex flex-col gap-1">
                    <span className={row.candidate.unparseable ? "font-medium text-fg" : undefined}>
                      {row.candidate.outcome}
                    </span>
                    <span>{row.candidate.confidence}</span>
                    <span>{row.candidate.issues}</span>
                    {row.candidate.needsReview ? (
                      <span className="text-xs font-medium text-fg">
                        {t("reviewQueue.candidate.needsReview")}
                      </span>
                    ) : null}
                  </div>
                )}
              </TableCell>
              <TableCell className="align-top text-sm">
                <div className="flex flex-col items-start gap-1">
                  {row.claimedBy === null ? (
                    <span className="text-fg-muted">{t("reviewQueue.unclaimed")}</span>
                  ) : (
                    <span>
                      {t("reviewQueue.claimedBy")} <PersonName person={row.claimedBy} />
                      {row.claimedAt === null ? null : (
                        <span className="block text-xs text-fg-muted">{row.claimedAt}</span>
                      )}
                    </span>
                  )}
                  {row.mine ? (
                    <Badge tone="info" data-slot="mine">
                      {t("reviewQueue.mine")}
                    </Badge>
                  ) : null}
                  {claim !== null && row.claimable ? (
                    <form
                      ref={(element) => {
                        forms.current[index] = element;
                      }}
                      onSubmit={(event) => {
                        event.preventDefault();
                        setActive(index);
                        send(new FormData(event.currentTarget));
                      }}
                    >
                      <input type="hidden" name={CLAIM_FIELD} value={row.taskId} />
                      <Button
                        type="submit"
                        size="sm"
                        variant="secondary"
                        disabled={pending}
                        aria-busy={pending || undefined}
                        aria-label={t("reviewQueue.claimNamed", { title: row.title })}
                      >
                        {t("reviewQueue.claim")}
                      </Button>
                    </form>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="align-top text-sm">
                <div className="flex flex-col items-start gap-1">
                  <StatusChip
                    status={row.status}
                    tone={TONES[row.status as keyof typeof TONES] ?? "neutral"}
                    label={row.statusLabel}
                  />
                  {row.decision === null ? null : (
                    <span className="text-xs text-fg-muted">
                      {row.decision.label}
                      {row.decision.by === null ? null : (
                        <>
                          {" "}
                          {t("reviewQueue.by")} <PersonName person={row.decision.by} />
                        </>
                      )}
                      {row.decision.at === null ? null : (
                        <span className="block">{row.decision.at}</span>
                      )}
                    </span>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent data-slot="shortcuts-dialog">
          <DialogHeader>
            <DialogTitle>{t("reviewQueue.keys.title")}</DialogTitle>
            <DialogDescription>{t("reviewQueue.keys.description")}</DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            {(
              [
                ["j", t("reviewQueue.keys.next")],
                ["k", t("reviewQueue.keys.previous")],
                [t("reviewQueue.keys.enterKey"), t("reviewQueue.keys.open")],
                ["c", t("reviewQueue.keys.claim")],
                ["?", t("reviewQueue.keys.help")],
              ] as const
            ).map(([key, what]) => (
              <div key={key} className="contents">
                <dt>
                  <kbd className="rounded-sm border border-line-strong px-1.5 font-mono text-xs">
                    {key}
                  </kbd>
                </dt>
                <dd className="text-fg">{what}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </div>
  );
}
