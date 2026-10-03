/**
 * The data rights screen's model: requests for access, rectification, erasure or data portability
 * under data protection regulations, with their status and resolution dates.
 */

export type DataRightType = "access" | "rectification" | "erasure" | "portability";
export type DataRightStatus = "pending" | "processing" | "fulfilled" | "rejected";

export interface DataRight {
  id: string;
  type: DataRightType;
  status: DataRightStatus;
  /** ISO instant. */
  requestedAt: string;
  /** ISO instant, or empty when not yet resolved. */
  resolvedAt: string;
  description: string;
}

export interface DataRightsView {
  rights: readonly DataRight[];
  totalCount: number;
}

export function emptyDataRights(): DataRightsView {
  return { rights: [], totalCount: 0 };
}
