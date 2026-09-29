/** Joins the ids that describe a control, skipping empties, for aria-describedby. */
export function describedBy(...ids: (string | false | null | undefined)[]): string | undefined {
  const joined = ids.filter((id): id is string => typeof id === "string" && id !== "").join(" ");
  return joined === "" ? undefined : joined;
}

export interface FieldIds {
  control: string;
  description: string;
  error: string;
}

/** The ids a Field derives from its control id: `<id>-description` and `<id>-error`. */
export function fieldIds(id: string): FieldIds {
  return { control: id, description: `${id}-description`, error: `${id}-error` };
}
