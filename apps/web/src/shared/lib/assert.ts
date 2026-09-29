/** Runtime assertions for invariants the types cannot express. */
export class AssertionError extends Error {
  override readonly name = "AssertionError";
}

export function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new AssertionError(message);
}

/** Exhaustiveness check for switch statements over unions. */
export function assertNever(value: never, message = "unexpected value"): never {
  throw new AssertionError(`${message}: ${JSON.stringify(value)}`);
}

/** Narrows away null and undefined with a message naming what was missing. */
export function unwrap<T>(value: T | null | undefined, message: string): T {
  assert(value !== null && value !== undefined, message);
  return value;
}
