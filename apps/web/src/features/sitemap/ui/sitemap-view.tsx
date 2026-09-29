import type { Route } from "next";
import Link from "next/link";
import {
  PageHeader,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { AwaitedItemView } from "@/entities/screen/types";
import { t } from "@/shared/i18n";
import { ScreenStatusChip } from "@/shared/ui/screen-status-chip";
import { countRows } from "../model/rows";
import type { SitemapRow, SitemapSection } from "../model/rows";

export interface SitemapViewProps {
  sections: readonly SitemapSection[];
}

const SHOWN_AWAITS = 3;

/** The awaited routes of a row, the first few in full and the rest as a count. */
export function AwaitedList({ items }: { items: readonly AwaitedItemView[] }) {
  if (items.length === 0) return <span className="text-fg-muted">{t("common.none")}</span>;
  const shown = items.slice(0, SHOWN_AWAITS);
  const rest = items.length - shown.length;
  return (
    <ul className="flex flex-col gap-1">
      {shown.map((item) => (
        <li key={`${item.method} ${item.path}`} className="flex flex-wrap items-center gap-1">
          <code className="rounded-sm bg-surface px-1 py-0.5 font-mono text-xs text-fg">
            {item.method} {item.path}
          </code>
          <span className="text-xs text-fg-muted">{item.owner}</span>
        </li>
      ))}
      {rest > 0 ? (
        <li className="text-xs text-fg-muted">{t("sitemap.more", { count: rest })}</li>
      ) : null}
    </ul>
  );
}

function ScreenCell({ row }: { row: SitemapRow }) {
  return (
    <div className="flex flex-col gap-1">
      {row.href === null ? (
        <span className="font-medium text-fg">{row.title}</span>
      ) : (
        <Link href={row.href as Route} className="font-medium text-primary hover:underline">
          {row.title}
        </Link>
      )}
      {row.kind !== "page" ? (
        <span className="text-xs text-fg-muted">{t(`sitemap.kind.${row.kind}`)}</span>
      ) : null}
      {row.links.length > 0 ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {row.links.map((link) => (
            <li key={link.href}>
              <Link href={link.href as Route} className="text-primary hover:underline">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      <span className="text-xs text-fg-muted">{row.id}</span>
    </div>
  );
}

/** Every registered screen, section by section, with its route, roles, status and awaited routes. */
export function SitemapView({ sections }: SitemapViewProps) {
  return (
    <div data-slot="sitemap" className="flex flex-col gap-8">
      <PageHeader
        title={t("sitemap.title")}
        description={`${t("sitemap.intro")} ${t("sitemap.count", { count: countRows(sections) })}`}
      />
      {sections.map((section) => (
        <Table key={section.key} data-section={section.key}>
          <TableCaption className="text-left text-base font-semibold text-fg">
            {t(`sitemap.section.${section.key}`)}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("sitemap.column.screen")}</TableHead>
              <TableHead>{t("sitemap.column.route")}</TableHead>
              <TableHead>{t("sitemap.column.roles")}</TableHead>
              <TableHead>{t("sitemap.column.status")}</TableHead>
              <TableHead>{t("sitemap.column.waitsFor")}</TableHead>
              <TableHead>{t("sitemap.column.guideRef")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {section.rows.map((row) => (
              <TableRow key={row.id} data-screen={row.id}>
                <TableCell className="align-top whitespace-normal">
                  <ScreenCell row={row} />
                </TableCell>
                <TableCell className="align-top">
                  <code className="font-mono text-xs text-fg">{row.route}</code>
                </TableCell>
                <TableCell className="align-top whitespace-normal text-fg-muted">
                  {row.roles.join(", ")}
                </TableCell>
                <TableCell className="align-top">
                  <ScreenStatusChip status={row.status} />
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  <AwaitedList items={row.waitsFor} />
                </TableCell>
                <TableCell className="align-top whitespace-normal text-fg-muted">
                  {row.guideRef}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ))}
    </div>
  );
}
