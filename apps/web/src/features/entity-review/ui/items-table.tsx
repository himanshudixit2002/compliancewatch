import type { Route } from "next";
import Link from "next/link";
import {
  Checkbox,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { GROUP_ITEMS_MAX, isCapped, type ItemRow } from "./decision-shared";

export interface ItemsTableProps {
  items: readonly ItemRow[];
  /** The group's name as shown, for the caption. */
  nameLabel: string;
  /** With a decision form: which mentions it names, and how a box changes that. */
  selection?: {
    selected: ReadonlySet<string>;
    onToggle: (reviewId: string, checked: boolean) => void;
    disabled?: boolean;
  };
}

/**
 * A group's open mentions: the text as found, why alignment could not settle it, and a link to
 * the document with the mention marked. With a selection, each row has a box: a decision names
 * the checked mentions, or every open mention of the group when none is checked.
 */
export function ItemsTable({ items, nameLabel, selection }: ItemsTableProps) {
  return (
    <Table scrollLabel={t("entityReview.items.region")} data-slot="review-items">
      <TableCaption className="text-left text-sm text-fg-muted">
        {isCapped(items.length)
          ? t("entityReview.items.captionCapped", { max: GROUP_ITEMS_MAX, name: nameLabel })
          : t("entityReview.items.caption", { count: items.length, name: nameLabel })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          {selection === undefined ? null : (
            <TableHead className="w-12">{t("entityReview.items.select")}</TableHead>
          )}
          <TableHead>{t("entityReview.items.mention")}</TableHead>
          <TableHead>{t("entityReview.items.reason")}</TableHead>
          <TableHead>{t("entityReview.items.document")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.reviewId} data-review-id={item.reviewId}>
            {selection === undefined ? null : (
              <TableCell className="align-top">
                <Checkbox
                  aria-label={t("entityReview.items.selectOne", { text: item.text })}
                  checked={selection.selected.has(item.reviewId)}
                  disabled={selection.disabled}
                  onCheckedChange={(checked) => selection.onToggle(item.reviewId, checked === true)}
                />
              </TableCell>
            )}
            <TableCell className="align-top text-sm whitespace-pre-wrap text-fg">
              {item.text}
            </TableCell>
            <TableCell className="align-top text-sm">{item.reasonLabel}</TableCell>
            <TableCell className="align-top text-sm">
              <Link
                href={item.documentHref as Route}
                className="text-primary underline-offset-2 hover:underline"
              >
                {t("entityReview.items.showInDocument")}
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
