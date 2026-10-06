import "server-only";

import { createHash, randomBytes } from "node:crypto";

/**
 * A multipart/form-data upload read as it arrives, never held whole. The browser's form sends its
 * text fields first and the file last (the upload form builds its body in that order); the head,
 * every part before the file's, is read into memory up to a small allowance and parsed; the file's
 * bytes then pass through untouched, counted and hashed, until the closing delimiter. What goes on
 * to the service is a new body with a boundary of its own: the fields the server chose (the actor
 * from the session, the checked values) and then the same file bytes, so nothing the browser sent
 * outside the file reaches the service as it was sent.
 *
 *   readUploadHead(reader, boundary, allowance)  the fields and the file part's headers, with the
 *                                                 file's first bytes already read
 *   fileBody(head, ...)                           the new body as a stream: the new fields, the
 *                                                 file's bytes, the closing delimiter
 *
 * A failure is an `UploadFormError` with the reason; a stream that fails part-way records it in
 * `FileBody.failure` before erroring, so the caller can tell its own refusal from a network one.
 */
export type UploadFormFailure =
  /** Not multipart, a part without a name, the file missing, a part after the file. */
  | "malformed"
  /** The fields before the file pass the allowance, or the file passes the limit. */
  | "too_large";

export class UploadFormError extends Error {
  override readonly name = "UploadFormError";
  readonly failure: UploadFormFailure;

  constructor(failure: UploadFormFailure, message: string) {
    super(message);
    this.failure = failure;
  }
}

const CRLF = Buffer.from("\r\n");
const HEADER_END = Buffer.from("\r\n\r\n");
const CLOSE = Buffer.from("--");

/** The boundary of a `multipart/form-data` content type, or null for anything else. */
export function boundaryOf(contentType: string | null): string | null {
  if (contentType === null) return null;
  const [kind, ...params] = contentType.split(";");
  if (kind?.trim().toLowerCase() !== "multipart/form-data") return null;
  for (const param of params) {
    const [name, ...rest] = param.split("=");
    if (name?.trim().toLowerCase() !== "boundary") continue;
    let value = rest.join("=").trim();
    if (value.startsWith('"') && value.endsWith('"') && value.length >= 2) {
      value = value.slice(1, -1);
    }
    // RFC 2046: 1 to 70 characters of a restricted set.
    return /^[0-9A-Za-z'()+_,\-./:=? ]{1,70}$/.test(value) && !value.endsWith(" ") ? value : null;
  }
  return null;
}

/** A part's headers: its Content-Disposition name and filename, and its Content-Type. */
export interface PartHeaders {
  name: string;
  filename: string | null;
  contentType: string | null;
}

function dispositionParam(disposition: string, param: string): string | null {
  const pattern = new RegExp(`;\\s*${param}="((?:[^"\\\\]|\\\\.)*)"`, "i");
  const quoted = pattern.exec(disposition);
  if (quoted !== null) return (quoted[1] ?? "").replace(/\\(.)/g, "$1");
  const bare = new RegExp(`;\\s*${param}=([^;\\s]+)`, "i").exec(disposition);
  return bare === null ? null : (bare[1] ?? null);
}

/** The headers of one part, or null when it names no form field. */
export function parsePartHeaders(block: string): PartHeaders | null {
  let disposition: string | null = null;
  let contentType: string | null = null;
  for (const line of block.split("\r\n")) {
    const colon = line.indexOf(":");
    if (colon <= 0) continue;
    const name = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    if (name === "content-disposition") disposition = value;
    if (name === "content-type") contentType = value;
  }
  if (disposition === null || !/^form-data\b/i.test(disposition)) return null;
  const name = dispositionParam(disposition, "name");
  if (name === null || name === "") return null;
  return { name, filename: dispositionParam(disposition, "filename"), contentType };
}

/** What the head held: the fields by name (the first of a repeated one) and the file part. */
export interface UploadHead {
  fields: ReadonlyMap<string, string>;
  file: PartHeaders;
  /** The file's bytes read with the head. */
  leftover: Buffer;
  boundary: string;
}

/** Reads from the stream until the head is whole; the file's bytes stay unread but for the first. */
export async function readUploadHead(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  boundary: string,
  allowance: number,
  fileField = "file",
): Promise<UploadHead> {
  const opening = Buffer.from(`--${boundary}`);
  const delimiter = Buffer.from(`\r\n--${boundary}`);
  let buffer = Buffer.alloc(0);
  let done = false;
  // Called only while the head is incomplete, so what is read already is all head: past the
  // allowance, the fields are too long (a chunk may carry the file's first bytes too, which is why
  // the length is checked before a read rather than after it).
  const more = async (): Promise<boolean> => {
    if (done) return false;
    if (buffer.length >= allowance) {
      throw new UploadFormError("too_large", "the fields before the file pass the allowance");
    }
    const next = await reader.read();
    if (next.done) {
      done = true;
      return false;
    }
    buffer = Buffer.concat([buffer, Buffer.from(next.value)]);
    return true;
  };
  const malformed = (why: string) => new UploadFormError("malformed", why);

  // The first delimiter, after any preamble, then CRLF.
  let start = buffer.indexOf(opening);
  while (start === -1 || buffer.length < start + opening.length + 2) {
    if (!(await more())) throw malformed("the body has no part");
    start = buffer.indexOf(opening);
  }
  let cursor = start + opening.length;
  const fields = new Map<string, string>();
  for (;;) {
    if (buffer.subarray(cursor, cursor + 2).equals(CLOSE)) {
      throw malformed(`the form has no ${fileField} part`);
    }
    if (!buffer.subarray(cursor, cursor + 2).equals(CRLF)) throw malformed("a delimiter is broken");
    cursor += 2;
    let headerEnd = buffer.indexOf(HEADER_END, cursor);
    while (headerEnd === -1) {
      if (!(await more())) throw malformed("a part's headers do not end");
      headerEnd = buffer.indexOf(HEADER_END, cursor);
    }
    const headers = parsePartHeaders(buffer.subarray(cursor, headerEnd).toString("latin1"));
    if (headers === null) throw malformed("a part names no form field");
    const bodyStart = headerEnd + HEADER_END.length;
    if (headers.name === fileField) {
      return { fields, file: headers, leftover: buffer.subarray(bodyStart), boundary };
    }
    let end = buffer.indexOf(delimiter, bodyStart);
    while (end === -1 || buffer.length < end + delimiter.length + 2) {
      if (!(await more())) throw malformed(`the field ${headers.name} does not end`);
      end = buffer.indexOf(delimiter, bodyStart);
    }
    if (!fields.has(headers.name)) {
      fields.set(headers.name, buffer.subarray(bodyStart, end).toString("utf8"));
    }
    cursor = end + delimiter.length;
  }
}

/** A boundary for the body sent on, which no file's bytes will hold by chance. */
export function newBoundary(): string {
  return `cw-upload-${randomBytes(16).toString("hex")}`;
}

/** One text part of the body sent on. */
export function textPart(boundary: string, name: string, value: string): Buffer {
  return Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n`),
    Buffer.from(value, "utf8"),
    CRLF,
  ]);
}

/** The headers of the file part of the body sent on; the filename is the server's. */
export function filePartHead(boundary: string, filename: string, contentType: string): Buffer {
  return Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
      `Content-Type: ${contentType}\r\n\r\n`,
  );
}

export interface FileBody {
  stream: ReadableStream<Uint8Array>;
  /** The file's bytes so far. */
  size(): number;
  /** The SHA-256 of the file's bytes, once the stream has ended; null before. */
  sha256(): string | null;
  /** Why the stream failed, when it was this module's refusal. */
  failure(): UploadFormError | null;
}

/**
 * The body sent on: `prefix` (the new fields and the file part's headers), then the file's bytes
 * from the head's leftover and the rest of the stream, up to the browser's closing delimiter, then
 * the new closing delimiter. A part after the file, a body that ends without its closing
 * delimiter, or more than `maxFileBytes` of file fail the stream with the reason recorded.
 */
export function fileBody(
  head: UploadHead,
  reader: ReadableStreamDefaultReader<Uint8Array>,
  prefix: Buffer,
  outgoingBoundary: string,
  maxFileBytes: number,
): FileBody {
  const delimiter = Buffer.from(`\r\n--${head.boundary}`);
  const keep = delimiter.length + CLOSE.length - 1;
  const hash = createHash("sha256");
  let pending = Buffer.from(head.leftover);
  let size = 0;
  let digest: string | null = null;
  let failure: UploadFormError | null = null;
  let finished = false;
  let readerDone = false;

  const fail = (
    controller: ReadableStreamDefaultController<Uint8Array>,
    error: UploadFormError,
  ) => {
    failure = error;
    controller.error(error);
    void reader.cancel(error.message).catch(() => undefined);
  };
  const emit = (
    controller: ReadableStreamDefaultController<Uint8Array>,
    bytes: Buffer,
  ): boolean => {
    if (bytes.length === 0) return true;
    size += bytes.length;
    if (size > maxFileBytes) {
      fail(controller, new UploadFormError("too_large", `the file passes ${maxFileBytes} bytes`));
      return false;
    }
    hash.update(bytes);
    controller.enqueue(new Uint8Array(bytes));
    return true;
  };
  const read = async (): Promise<boolean> => {
    if (readerDone) return false;
    const next = await reader.read();
    if (next.done) {
      readerDone = true;
      return false;
    }
    pending = Buffer.concat([pending, Buffer.from(next.value)]);
    return true;
  };

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(prefix));
    },
    async pull(controller) {
      if (finished) return;
      for (;;) {
        const index = pending.indexOf(delimiter);
        if (index !== -1 && pending.length >= index + delimiter.length + CLOSE.length) {
          if (!emit(controller, pending.subarray(0, index))) return;
          const after = pending.subarray(index + delimiter.length, index + delimiter.length + 2);
          if (!after.equals(CLOSE)) {
            fail(controller, new UploadFormError("malformed", "a part follows the file"));
            return;
          }
          finished = true;
          digest = hash.digest("hex");
          controller.enqueue(new Uint8Array(Buffer.from(`\r\n--${outgoingBoundary}--\r\n`)));
          controller.close();
          void reader.cancel().catch(() => undefined);
          return;
        }
        if (index === -1 && pending.length > keep) {
          const ready = pending.length - keep;
          const chunk = pending.subarray(0, ready);
          pending = pending.subarray(ready);
          emit(controller, chunk);
          return;
        }
        if (!(await read())) {
          fail(controller, new UploadFormError("malformed", "the body ends inside the file"));
          return;
        }
      }
    },
    cancel(reason) {
      void reader.cancel(reason).catch(() => undefined);
    },
  });

  return {
    stream,
    size: () => size,
    sha256: () => digest,
    failure: () => failure,
  };
}
