/**
 * What a server action returns to a form: the state `useActionState` holds between submits.
 * Isomorphic on purpose: client form components read it, server actions build it (the
 * server-side mapping from a service Result lives in server/result.ts).
 *
 *   idle   nothing submitted yet
 *   ok     the action succeeded; `value` is what it produced, `message` what to announce
 *   error  an expected failure: the service's problem (title, detail and the correlation id to
 *          quote to support), errors per field (from a 422 `errors[].loc` or a form check) and
 *          errors for the form as a whole (a refused flag, a missing precondition)
 *
 * Unexpected exceptions are not states: they propagate to the segment's error boundary.
 */
export interface ActionProblem {
  /** The problem type URN, or a web-local one (`urn:compliancewatch:problem:web-*`). */
  type: string;
  title: string;
  detail?: string;
  /** The x-request-id the server layer sent, echoed by the service; the log line to search for. */
  correlationId?: string;
}

export type FieldErrors = Readonly<Record<string, readonly string[]>>;

export type ActionState<T = undefined> =
  | { status: "idle" }
  | { status: "ok"; value?: T; message?: string }
  | {
      status: "error";
      problem?: ActionProblem;
      fieldErrors?: FieldErrors;
      formErrors?: readonly string[];
    };

export function idleAction<T = undefined>(): ActionState<T> {
  return { status: "idle" };
}

export function actionSuccess<T>(value?: T, message?: string): ActionState<T> {
  return message === undefined ? { status: "ok", value } : { status: "ok", value, message };
}

/** A failure that is not a service problem: a refused flag, a form-level check. */
export function actionFailure<T = undefined>(
  formErrors: string | readonly string[],
  fieldErrors?: FieldErrors,
): ActionState<T> {
  const errors = typeof formErrors === "string" ? [formErrors] : formErrors;
  return fieldErrors === undefined
    ? { status: "error", formErrors: errors }
    : { status: "error", formErrors: errors, fieldErrors };
}

/** A failure on named fields only, for a form check before any service is called. */
export function fieldFailure<T = undefined>(fieldErrors: FieldErrors): ActionState<T> {
  return { status: "error", fieldErrors };
}

/** The first message recorded for a field, for `<Field error={...}>`. */
export function fieldErrorOf<T>(state: ActionState<T>, field: string): string | undefined {
  return state.status === "error" ? state.fieldErrors?.[field]?.[0] : undefined;
}
