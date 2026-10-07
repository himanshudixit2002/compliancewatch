/**
 * A line diff without a library: the longest common subsequence of two lists of lines, read back
 * as the lines both share, the lines only the first has (removed) and the lines only the second
 * has (added), in reading order, a removal before the addition that replaces it. The lists the
 * app compares are short (a field's value, a condition in words), so the plain quadratic table is
 * enough; past `MAX_CELLS` the diff gives up on alignment and lists every line as removed, then
 * added, which is still correct, only coarser.
 */
export type DiffKind = "same" | "removed" | "added";

export interface DiffLine {
  kind: DiffKind;
  text: string;
}

/** The largest table the diff fills before it stops aligning lines. */
export const MAX_CELLS = 250_000;

export function diffLines(before: readonly string[], after: readonly string[]): DiffLine[] {
  const rows = before.length;
  const columns = after.length;
  if (rows * columns > MAX_CELLS) {
    return [
      ...before.map((text): DiffLine => ({ kind: "removed", text })),
      ...after.map((text): DiffLine => ({ kind: "added", text })),
    ];
  }
  // lengths[i][j]: the longest common subsequence of before[i..] and after[j..].
  const lengths: number[][] = Array.from({ length: rows + 1 }, () =>
    new Array<number>(columns + 1).fill(0),
  );
  for (let i = rows - 1; i >= 0; i -= 1) {
    const row = lengths[i] as number[];
    const below = lengths[i + 1] as number[];
    for (let j = columns - 1; j >= 0; j -= 1) {
      row[j] =
        before[i] === after[j]
          ? (below[j + 1] as number) + 1
          : Math.max(below[j] as number, row[j + 1] as number);
    }
  }
  const lines: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < rows && j < columns) {
    if (before[i] === after[j]) {
      lines.push({ kind: "same", text: before[i] as string });
      i += 1;
      j += 1;
    } else if (
      ((lengths[i + 1] as number[])[j] as number) >= ((lengths[i] as number[])[j + 1] as number)
    ) {
      lines.push({ kind: "removed", text: before[i] as string });
      i += 1;
    } else {
      lines.push({ kind: "added", text: after[j] as string });
      j += 1;
    }
  }
  for (; i < rows; i += 1) lines.push({ kind: "removed", text: before[i] as string });
  for (; j < columns; j += 1) lines.push({ kind: "added", text: after[j] as string });
  return lines;
}

/** Whether a diff holds any line that is not shared. */
export function hasChanges(lines: readonly DiffLine[]): boolean {
  return lines.some((line) => line.kind !== "same");
}
