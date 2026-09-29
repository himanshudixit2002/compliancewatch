import {
  KeyValue,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { SnapshotView as SnapshotViewModel } from "../model/business-pages";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";
import { NodeYearPicker } from "./node-year-picker";

export interface SnapshotViewProps {
  title: string;
  view: SnapshotViewModel;
  header: Omit<BusinessPageHeaderProps, "title" | "description">;
  pageHref: string;
  nodeHref: (nodeId: string) => string;
}

/**
 * The snapshot of a node for a financial year: what the applicability engine evaluates, with
 * where each value comes from (stored on this node, inherited from a named ancestor, or worked
 * out by the service) and the profile version it was read at.
 */
export function SnapshotView({ title, view, header, pageHref, nodeHref }: SnapshotViewProps) {
  const { node } = view;
  return (
    <div data-slot="snapshot-view" className="flex max-w-4xl flex-col gap-6">
      <BusinessPageHeader
        {...header}
        title={title}
        description={t("business.pageIntro", { name: view.header.name, pan: view.header.pan })}
      />
      <NodeYearPicker
        action={pageHref}
        nodes={view.nodes}
        currentNodeId={node.id}
        fy={view.fy}
        fyChoices={view.fyChoices}
        nodeHref={nodeHref}
      />
      <p className="max-w-prose text-sm text-fg-muted">{t("snapshot.intro")}</p>
      <KeyValue
        items={[
          { key: "node", label: t("snapshot.node"), value: node.display },
          { key: "fy", label: t("business.financialYear"), value: view.fy },
          { key: "version", label: t("business.version"), value: String(view.version) },
        ]}
      />
      {view.rows.length === 0 ? (
        <p className="text-sm text-fg-muted">{t("snapshot.empty")}</p>
      ) : (
        <Table data-slot="snapshot-table" scrollLabel={t("snapshot.caption", { fy: view.fy })}>
          <TableCaption>{t("snapshot.caption", { fy: view.fy })}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("attributes.column.attribute")}</TableHead>
              <TableHead>{t("snapshot.value")}</TableHead>
              <TableHead>{t("snapshot.origin")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.rows.map((row) => (
              <TableRow key={row.key} data-attribute={row.key}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell>{row.valueText}</TableCell>
                <TableCell>{row.originLabel}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
