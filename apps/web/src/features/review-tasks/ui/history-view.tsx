import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { HistoryView as HistoryModel } from "../model/history";
import { PersonName } from "./write-result";

export interface HistoryViewProps {
  history: HistoryModel;
}

/**
 * The history: the version's decision audit as the rulebook keeps it (newest first: each
 * submission, return, approval, publication and edit, by whom and why), then every review task
 * the version or its candidate has had, oldest first, the current one marked.
 */
export function HistoryView({ history }: HistoryViewProps) {
  return (
    <section
      aria-labelledby="workbench-history"
      data-slot="history"
      className="flex flex-col gap-4"
    >
      <h2 id="workbench-history" className="text-lg font-semibold text-fg">
        {t("workbench.history.heading")}
      </h2>
      <div className="flex flex-col gap-2" data-slot="history-audit">
        <h3 className="text-base font-semibold text-fg">{t("workbench.history.auditHeading")}</h3>
        {history.audit.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("workbench.history.noAudit")}</p>
        ) : (
          <Table scrollLabel={t("workbench.history.auditRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("workbench.history.auditCaption", { count: history.audit.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("workbench.history.column.when")}</TableHead>
                <TableHead scope="col">{t("workbench.history.column.what")}</TableHead>
                <TableHead scope="col">{t("workbench.history.column.who")}</TableHead>
                <TableHead scope="col">{t("workbench.history.column.note")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.audit.map((row) => (
                <TableRow key={row.decisionId} data-decision={row.decisionId}>
                  <TableCell className="align-top text-sm whitespace-nowrap">{row.at}</TableCell>
                  <TableCell className="align-top text-sm">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">{row.action}</span>
                      <span className="text-xs text-fg-muted">{row.move}</span>
                      {row.causedBy === null ? null : (
                        <Link
                          href={row.causedBy.href as Route}
                          className="text-xs text-primary underline-offset-2 hover:underline"
                        >
                          {t("workbench.history.causedBy")}
                        </Link>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm">
                    {row.actor === null ? (
                      t("workbench.history.system")
                    ) : (
                      <PersonName person={row.actor} />
                    )}
                  </TableCell>
                  <TableCell className="align-top text-sm whitespace-pre-wrap">
                    {row.note === "" ? (
                      <span className="text-fg-muted">{t("common.none")}</span>
                    ) : (
                      row.note
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      <div className="flex flex-col gap-2" data-slot="history-tasks">
        <h3 className="text-base font-semibold text-fg">{t("workbench.history.tasksHeading")}</h3>
        <Table scrollLabel={t("workbench.history.tasksRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("workbench.history.tasksCaption", { count: history.tasks.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{t("workbench.history.column.task")}</TableHead>
              <TableHead scope="col">{t("workbench.history.column.opened")}</TableHead>
              <TableHead scope="col">{t("workbench.history.column.claimed")}</TableHead>
              <TableHead scope="col">{t("workbench.history.column.decision")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {history.tasks.map((row) => (
              <TableRow
                key={row.taskId}
                data-task={row.taskId}
                data-current={row.current || undefined}
              >
                <TableCell className="align-top text-sm">
                  <div className="flex flex-col items-start gap-1">
                    {row.current ? (
                      <span className="font-medium">{t("workbench.history.thisTask")}</span>
                    ) : (
                      <Link
                        href={row.href as Route}
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        {t("workbench.history.openTask")}
                      </Link>
                    )}
                    <span className="text-xs text-fg-muted">
                      {row.kind}, {row.status}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="align-top text-sm whitespace-nowrap">{row.opened}</TableCell>
                <TableCell className="align-top text-sm">
                  {row.claimed === null ? (
                    <span className="text-fg-muted">{t("reviewQueue.unclaimed")}</span>
                  ) : (
                    <span>
                      <PersonName person={row.claimed.by} />
                      {row.claimed.at === null ? null : (
                        <span className="block text-xs text-fg-muted">{row.claimed.at}</span>
                      )}
                    </span>
                  )}
                </TableCell>
                <TableCell className="align-top text-sm">
                  {row.decision === null ? (
                    <Badge tone="neutral">{t("workbench.history.undecided")}</Badge>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">{row.decision.label}</span>
                      {row.decision.by === null ? null : (
                        <span>
                          {t("reviewQueue.by")} <PersonName person={row.decision.by} />
                        </span>
                      )}
                      {row.decision.at === null ? null : (
                        <span className="text-xs text-fg-muted">{row.decision.at}</span>
                      )}
                      {row.decision.note === "" ? null : (
                        <span className="text-xs whitespace-pre-wrap">{row.decision.note}</span>
                      )}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
