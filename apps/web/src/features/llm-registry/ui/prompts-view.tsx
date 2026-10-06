import {
  CopyButton,
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { EditNote as EditNoteView, PromptRow } from "../model/registry";
import { EditNote } from "./edit-note";

export interface PromptsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  rows: readonly PromptRow[];
  note: EditNoteView;
}

/**
 * The prompts the LLM gateway serves: each name and version with its owner, how many eval cases
 * guard it (none is flagged), the hash of its text and what it is for. Read-only: a prompt
 * changes with a release of the gateway's registry, and the page says what in-app edits wait for.
 */
export function PromptsView({ title, crumbs, rows, note }: PromptsViewProps) {
  return (
    <div data-slot="llm-prompts" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("llm.prompts.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <EditNote note={note} />
      {rows.length === 0 ? (
        <EmptyState title={t("llm.prompts.emptyTitle")} body={t("llm.prompts.emptyBody")} />
      ) : (
        <Table scrollLabel={t("llm.prompts.tableRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("llm.prompts.caption", { count: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("llm.prompts.column.prompt")}</TableHead>
              <TableHead>{t("llm.prompts.column.owner")}</TableHead>
              <TableHead>{t("llm.prompts.column.evals")}</TableHead>
              <TableHead>{t("llm.prompts.column.hash")}</TableHead>
              <TableHead>{t("llm.prompts.column.description")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.key} data-prompt={row.key}>
                <TableCell className="align-top">
                  <code className="font-mono text-sm text-fg">{row.key}</code>
                </TableCell>
                <TableCell className="align-top text-sm">{row.owner}</TableCell>
                <TableCell className="align-top text-sm">
                  {row.unguarded ? (
                    <StatusChip status="no_evals" tone="warning" label={t("llm.prompts.noEvals")} />
                  ) : (
                    String(row.evalCases)
                  )}
                </TableCell>
                <TableCell className="align-top">
                  {row.sha256 === null || row.shortHash === null ? (
                    <span className="text-sm text-fg-muted">{t("common.none")}</span>
                  ) : (
                    <span className="flex items-center gap-1">
                      <code className="font-mono text-xs text-fg-muted">{row.shortHash}</code>
                      <CopyButton
                        value={row.sha256}
                        label={t("llm.prompts.copyHash", { prompt: row.key })}
                        size="sm"
                      />
                    </span>
                  )}
                </TableCell>
                <TableCell className="max-w-prose align-top text-sm">{row.description}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
