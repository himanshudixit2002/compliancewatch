import type { ProfileNode, ReviewTask } from "@/entities/business/types";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { t } from "@/shared/i18n";
import { attributeLabel } from "./attributes";

/**
 * Review tasks as rows: the attribute, why the task is open (the profile service's
 * ReviewReason worded for the owner), the year, when it opened in IST, and the node it is on.
 * The web app can only list them; resolving one is an analyst's action on the service.
 */
export interface ReviewTaskRow {
  id: string;
  attributeKey: string;
  attributeLabel: string;
  reason: string;
  reasonLabel: string;
  asOfFy: string | null;
  openedAt: string;
  open: boolean;
  statusLabel: string;
  nodeId: string;
  /** The node's name when the caller knows the node, else its id. */
  nodeName: string;
}

export function reviewReasonLabel(reason: string): string {
  switch (reason) {
    case "not_applicable":
    case "confirm_financial_year":
    case "verify_registration":
      return t(`reviewTask.reason.${reason}`);
    default:
      return humanise(reason);
  }
}

/** Open tasks first, then newest first. */
export function reviewTaskRows(
  tasks: readonly ReviewTask[],
  nodes: readonly ProfileNode[] = [],
): ReviewTaskRow[] {
  const names = new Map(nodes.map((node) => [node.id, node.name]));
  return [...tasks]
    .sort((a, b) => Number(b.open) - Number(a.open) || b.createdAt.localeCompare(a.createdAt))
    .map((task) => ({
      id: task.id,
      attributeKey: task.attributeKey,
      attributeLabel: attributeLabel(task.attributeKey),
      reason: task.reason,
      reasonLabel: reviewReasonLabel(task.reason),
      asOfFy: task.asOfFy,
      openedAt: formatDateTime(task.createdAt),
      open: task.open,
      statusLabel: task.open ? t("reviewTask.open") : t("reviewTask.closed"),
      nodeId: task.nodeId,
      nodeName: names.get(task.nodeId) ?? task.nodeId,
    }));
}
