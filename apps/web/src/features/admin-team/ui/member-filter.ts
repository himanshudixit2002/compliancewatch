import type { Tone } from "@compliancewatch/ui";

/**
 * What the client-side member table receives: each member with its wording and tones already
 * worked out on the server, and the pure filter it applies as the admin types or picks a role.
 */
export interface LabelledValue {
  value: string;
  label: string;
  tone: Tone;
}

export interface MemberRow {
  id: string;
  name: string;
  email: string;
  roles: readonly LabelledValue[];
  status: LabelledValue;
  /** The join date, already formatted. */
  joined: string;
}

/** The role filter's value that shows every member. */
export const ALL_ROLES = "all";

/**
 * Members whose name or email contains the query (ignoring case and surrounding spaces) and
 * who hold the role, unless the role is ALL_ROLES.
 */
export function filterMembers(
  rows: readonly MemberRow[],
  query: string,
  role: string,
): MemberRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (role !== ALL_ROLES && !row.roles.some((held) => held.value === role)) return false;
    if (needle === "") return true;
    return row.name.toLowerCase().includes(needle) || row.email.toLowerCase().includes(needle);
  });
}
