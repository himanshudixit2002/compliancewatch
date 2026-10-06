/**
 * The members of a string union, listed once. `membersOf<Union>({ ... })` returns the keys of a
 * `Record<Union, true>` in the order the record lists them. Given the union as the type argument
 * (or a record declared with that type), the record is checked against the union both ways: a
 * member it lacks, or a key the union does not hold, fails the build. A list of a service's enum
 * written this way breaks the build when the service adds a value (a gateway feature, a candidate
 * status), rather than leaving the value off a page.
 */
export function membersOf<T extends string>(record: Readonly<Record<T, true>>): readonly T[] {
  return Object.keys(record) as T[];
}
