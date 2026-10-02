import type { Route } from "next";
import Link from "next/link";
import { Button, Field, Select, cn } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { NodeRef } from "../model/business-pages";

export interface NodeYearPickerProps {
  /** The page itself, without a query. */
  action: string;
  nodes: readonly NodeRef[];
  currentNodeId: string;
  fy: string;
  fyChoices: readonly string[];
  /** The same page for another node, keeping the year. */
  nodeHref: (nodeId: string) => string;
}

/**
 * Which node and which financial year a page shows. The nodes are links (the business, each
 * registration, a location being shown), the current one marked; the year is a GET form, so the
 * choice is in the URL and the back button works. Node ids and year labels are not personal data.
 */
export function NodeYearPicker({
  action,
  nodes,
  currentNodeId,
  fy,
  fyChoices,
  nodeHref,
}: NodeYearPickerProps) {
  return (
    <div data-slot="node-year-picker" className="flex flex-col gap-4">
      <nav aria-label={t("business.nodePicker")}>
        <ul className="flex flex-wrap gap-2 text-sm">
          {nodes.map((node) => {
            const current = node.id === currentNodeId;
            return (
              <li key={node.id}>
                <Link
                  href={nodeHref(node.id) as Route}
                  aria-current={current ? "page" : undefined}
                  className={cn(
                    "inline-flex flex-col rounded-md border px-3 py-1.5",
                    current
                      ? "border-primary bg-primary/10 text-fg"
                      : "border-line text-fg-muted hover:text-fg",
                  )}
                >
                  <span className="font-medium">{node.name}</span>
                  <span className="text-xs">
                    {node.levelLabel}: {node.key}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <form method="get" action={action} className="flex flex-wrap items-end gap-2">
        <input type="hidden" name="node" value={currentNodeId} />
        <Field id="financial-year" label={t("business.financialYear")} className="w-40">
          <Select
            name="fy"
            defaultValue={fy}
            options={fyChoices.map((label) => ({ value: label, label }))}
          />
        </Field>
        <Button type="submit" variant="secondary" size="sm">
          {t("business.showYear")}
        </Button>
      </form>
    </div>
  );
}
