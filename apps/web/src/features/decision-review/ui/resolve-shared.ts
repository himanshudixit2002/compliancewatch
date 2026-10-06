/**
 * What the resolve panel and its server action share, in the ui directory so the client panel may
 * import it: the field names, the note's limits (the engine's: 1 to 2000 characters, checked again
 * in the action) and the shape of an answer.
 */
export const RESOLVE_FIELDS = {
  resolution: "resolution",
  note: "note",
} as const;

export const NOTE_MAX_LENGTH = 2000;

/** What a resolution answered: the sentence to announce. */
export interface ResolveResult {
  message: string;
}
