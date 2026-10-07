import type { TranscriptBlock } from "@/entities/pipeline/types";
import { t } from "@/shared/i18n";

/**
 * A manual parse's transcript typed as plain text, read into the blocks the pipeline's parsers
 * give (`TranscriptIn`): headings, numbered paragraphs and tables, in document order. Isomorphic,
 * so the panel shows what it will send and the action reads the same text again. The rules:
 *
 *   - blocks are separated by a blank line;
 *   - `# ` starts a heading;
 *   - a block whose every line starts with `|` is a table: its cells sit between the bars, and a
 *     second line of bars and dashes (`|---|---|`) makes the first line its header;
 *   - `[page 3]` on a line of its own gives the page of the blocks after it;
 *   - any other block is a paragraph, its lines joined by spaces; a leading number as printed
 *     (`1.`, `2A.`, `(3)`, `(a)`, `a)`, `(iv)`) becomes the paragraph's number.
 *
 * The limits are the pipeline's (and the rulebook's): 50,000 characters a heading, paragraph or
 * cell row, 50 cells a row, 2,000 rows a table and 2,000 clauses in all (a heading, a paragraph
 * or a table row each make one). The pipeline checks the transcript again and names each problem
 * by its place.
 */
export const TRANSCRIPT_LIMITS = {
  textMax: 50_000,
  cellsMax: 50,
  rowsMax: 2_000,
  clausesMax: 2_000,
  numberMax: 20,
} as const;

const PAGE = /^\[page\s+(\d{1,5})\]$/i;
const NUMBER = /^(\(?\d{1,4}[A-Za-z]?[.)]|\([a-z]{1,6}\)|[a-z]\))(?:\s+(.*))?$/;
const SEPARATOR = /^\|?(\s*:?-+:?\s*\|)*\s*:?-+:?\s*\|?$/;

export type TranscriptRead =
  | { ok: true; blocks: TranscriptBlock[] }
  | { ok: false; blocks: TranscriptBlock[]; errors: string[] };

function cells(line: string): string[] {
  let inner = line.trim();
  if (inner.startsWith("|")) inner = inner.slice(1);
  if (inner.endsWith("|")) inner = inner.slice(0, -1);
  return inner.split("|").map((cell) => cell.trim());
}

/** The clauses a block makes: one for a heading or a paragraph, one per row of a table. */
export function clausesOf(block: TranscriptBlock): number {
  return block.type === "table" ? block.rows.length : 1;
}

export interface BlockCounts {
  headings: number;
  paragraphs: number;
  tables: number;
  clauses: number;
}

export function blockCounts(blocks: readonly TranscriptBlock[]): BlockCounts {
  return {
    headings: blocks.filter((block) => block.type === "heading").length,
    paragraphs: blocks.filter((block) => block.type === "paragraph").length,
    tables: blocks.filter((block) => block.type === "table").length,
    clauses: blocks.reduce((sum, block) => sum + clausesOf(block), 0),
  };
}

export function readTranscript(text: string): TranscriptRead {
  const groups: { lines: string[]; page: number | null }[] = [];
  let current: string[] = [];
  let page: number | null = null;
  const flush = () => {
    if (current.length > 0) groups.push({ lines: current, page });
    current = [];
  };
  for (const raw of text.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    const marker = PAGE.exec(line);
    if (marker !== null) {
      flush();
      page = Number(marker[1]);
      continue;
    }
    if (line === "") {
      flush();
      continue;
    }
    current.push(line);
  }
  flush();

  const blocks: TranscriptBlock[] = [];
  const errors: string[] = [];
  groups.forEach((group, index) => {
    const where = index + 1;
    const [first = "", ...rest] = group.lines;
    if (group.lines.every((line) => line.startsWith("|"))) {
      const second = group.lines[1];
      const hasHeader = second !== undefined && SEPARATOR.test(second) && second.includes("-");
      const header = hasHeader ? cells(first) : null;
      const rows = (hasHeader ? group.lines.slice(2) : group.lines).map(cells);
      if (rows.length === 0) errors.push(t("pipelineTasks.transcript.noRows", { block: where }));
      if (rows.length > TRANSCRIPT_LIMITS.rowsMax) {
        errors.push(
          t("pipelineTasks.transcript.tooManyRows", {
            block: where,
            max: TRANSCRIPT_LIMITS.rowsMax,
          }),
        );
      }
      rows.forEach((row, rowIndex) => {
        if (row.every((cell) => cell === "")) {
          errors.push(t("pipelineTasks.transcript.emptyRow", { block: where, row: rowIndex + 1 }));
        }
        if (row.length > TRANSCRIPT_LIMITS.cellsMax) {
          errors.push(
            t("pipelineTasks.transcript.tooManyCells", {
              block: where,
              row: rowIndex + 1,
              max: TRANSCRIPT_LIMITS.cellsMax,
            }),
          );
        }
      });
      if (header !== null && header.length > TRANSCRIPT_LIMITS.cellsMax) {
        errors.push(
          t("pipelineTasks.transcript.tooManyCells", {
            block: where,
            row: 0,
            max: TRANSCRIPT_LIMITS.cellsMax,
          }),
        );
      }
      blocks.push({ type: "table", header, rows, page: group.page });
      return;
    }
    if (first.startsWith("# ") || first === "#") {
      const text = [first.replace(/^#\s*/, ""), ...rest].join(" ").trim();
      if (text === "") errors.push(t("pipelineTasks.transcript.emptyHeading", { block: where }));
      if (text.length > TRANSCRIPT_LIMITS.textMax) {
        errors.push(
          t("pipelineTasks.transcript.tooLong", { block: where, max: TRANSCRIPT_LIMITS.textMax }),
        );
      }
      blocks.push({ type: "heading", text, page: group.page });
      return;
    }
    const joined = group.lines.join(" ");
    const numbered = NUMBER.exec(joined);
    const number = numbered === null ? "" : (numbered[1] ?? "");
    const text = (numbered === null ? joined : (numbered[2] ?? "")).trim();
    if (text === "") errors.push(t("pipelineTasks.transcript.emptyParagraph", { block: where }));
    if (text.length > TRANSCRIPT_LIMITS.textMax) {
      errors.push(
        t("pipelineTasks.transcript.tooLong", { block: where, max: TRANSCRIPT_LIMITS.textMax }),
      );
    }
    blocks.push({ type: "paragraph", number, text, page: group.page });
  });
  if (blocks.length === 0) errors.push(t("pipelineTasks.transcript.empty"));
  const clauses = blocks.reduce((sum, block) => sum + clausesOf(block), 0);
  if (clauses > TRANSCRIPT_LIMITS.clausesMax) {
    errors.push(
      t("pipelineTasks.transcript.tooManyClauses", {
        count: clauses,
        max: TRANSCRIPT_LIMITS.clausesMax,
      }),
    );
  }
  return errors.length === 0 ? { ok: true, blocks } : { ok: false, blocks, errors };
}
