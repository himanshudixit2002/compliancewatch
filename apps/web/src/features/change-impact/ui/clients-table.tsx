import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ApplicabilityBadge } from "@/shared/ui/applicability";
import type { ClientRow } from "../model/impact";

export interface ClientsTableProps {
  clients: readonly ClientRow[];
}

/**
 * The firm's clients with a decision of the change: one row per business (a GSTIN registration,
 * or the client itself by its PAN) under its client, with the engine's latest result, whether a
 * person has to review it, how sure the engine was and when it decided.
 */
export function ClientsTable({ clients }: ClientsTableProps) {
  return (
    <Table data-slot="impact-clients" scrollLabel={t("changeImpact.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("changeImpact.caption", { count: clients.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("changeImpact.column.client")}</TableHead>
          <TableHead scope="col">{t("changeImpact.column.business")}</TableHead>
          <TableHead scope="col">{t("changeImpact.column.result")}</TableHead>
          <TableHead scope="col">{t("changeImpact.column.decided")}</TableHead>
        </TableRow>
      </TableHeader>
      {clients.map((client) => (
        <TableBody key={client.entityId} data-client={client.entityId}>
          {client.businesses.map((business, index) => (
            <TableRow
              key={business.businessId}
              data-business={business.businessId}
              data-result={business.result}
            >
              {index === 0 ? (
                <TableHead
                  scope="rowgroup"
                  rowSpan={client.businesses.length}
                  className="align-top font-medium whitespace-normal"
                >
                  {client.name}
                </TableHead>
              ) : null}
              <TableCell className="align-top whitespace-normal">{business.label}</TableCell>
              <TableCell className="align-top">
                <ApplicabilityBadge result={business.result} needsReview={business.needsReview} />
              </TableCell>
              <TableCell className="align-top whitespace-nowrap">
                <time dateTime={business.decidedIso}>{business.decided}</time>
                <span className="block text-xs text-fg-muted">
                  {t("changeImpact.confidence", { confidence: business.confidence })}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      ))}
    </Table>
  );
}
