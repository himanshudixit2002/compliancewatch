// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  UploadFormError,
  boundaryOf,
  fileBody,
  filePartHead,
  newBoundary,
  parsePartHeaders,
  readUploadHead,
  textPart,
} from "./multipart";

const BOUNDARY = "----ExampleBoundary0123456789";
const FILE = Buffer.from("%PDF-1.4\nExample file bytes\r\n--not-a-boundary\r\n%%EOF\n");

/** A browser-shaped body: the text fields, then the file, then whatever `tail` adds. */
function body(
  fields: Readonly<Record<string, string>>,
  file: Buffer | null = FILE,
  tail = "",
): Buffer {
  const parts: Buffer[] = [];
  for (const [name, value] of Object.entries(fields)) {
    parts.push(
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`,
      ),
    );
  }
  if (file !== null) {
    parts.push(
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="example.pdf"\r\n` +
          "Content-Type: application/pdf\r\n\r\n",
      ),
      file,
      Buffer.from(`\r\n${tail}`),
    );
  }
  parts.push(Buffer.from(`--${BOUNDARY}--\r\n`));
  return Buffer.concat(parts);
}

/** A reader over the bytes, `size` bytes a chunk. */
function chunked(bytes: Buffer, size: number): ReadableStreamDefaultReader<Uint8Array> {
  let offset = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(new Uint8Array(bytes.subarray(offset, offset + size)));
      offset += size;
    },
  }).getReader();
}

async function drain(stream: ReadableStream<Uint8Array>): Promise<Buffer> {
  const chunks: Buffer[] = [];
  const reader = stream.getReader();
  for (;;) {
    const next = await reader.read();
    if (next.done) return Buffer.concat(chunks);
    chunks.push(Buffer.from(next.value));
  }
}

const FIELDS = {
  reason: "Example reason for the upload",
  title: "Example title, line one\r\nline two",
};

describe("boundaryOf", () => {
  it("reads the boundary of multipart/form-data and nothing else", () => {
    expect(boundaryOf(`multipart/form-data; boundary=${BOUNDARY}`)).toBe(BOUNDARY);
    expect(boundaryOf('Multipart/Form-Data; charset=utf-8; boundary="quoted value"')).toBe(
      "quoted value",
    );
    expect(boundaryOf("application/json")).toBeNull();
    expect(boundaryOf("multipart/form-data")).toBeNull();
    expect(boundaryOf("multipart/form-data; boundary=")).toBeNull();
    expect(boundaryOf(`multipart/form-data; boundary=${"x".repeat(71)}`)).toBeNull();
    expect(boundaryOf("multipart/form-data; boundary=bad\u0000value")).toBeNull();
    expect(boundaryOf(null)).toBeNull();
  });
});

describe("parsePartHeaders", () => {
  it("reads the field name, the filename and the type", () => {
    expect(
      parsePartHeaders(
        'Content-Disposition: form-data; name="file"; filename="a \\"b\\".pdf"\r\nContent-Type: application/pdf',
      ),
    ).toEqual({ name: "file", filename: 'a "b".pdf', contentType: "application/pdf" });
    expect(parsePartHeaders("content-disposition: form-data; name=reason")).toEqual({
      name: "reason",
      filename: null,
      contentType: null,
    });
    expect(parsePartHeaders("Content-Disposition: attachment; name=x")).toBeNull();
    expect(parsePartHeaders('Content-Disposition: form-data; filename="x"')).toBeNull();
    expect(parsePartHeaders("Content-Type: text/plain")).toBeNull();
  });
});

describe("readUploadHead and fileBody", () => {
  for (const size of [1, 3, 17, 64, 4096]) {
    it(`reads the fields and passes the file through whole in chunks of ${size}`, async () => {
      const reader = chunked(body(FIELDS), size);
      const head = await readUploadHead(reader, BOUNDARY, 64 * 1024);
      expect(Object.fromEntries(head.fields)).toEqual(FIELDS);
      expect(head.file).toEqual({
        name: "file",
        filename: "example.pdf",
        contentType: "application/pdf",
      });
      const out = newBoundary();
      const prefix = Buffer.concat([
        textPart(out, "actor_id", "00000000-0000-4000-8000-000000000001"),
        filePartHead(out, "document.pdf", "application/pdf"),
      ]);
      const sent = fileBody(head, reader, prefix, out, 1024);
      const bytes = await drain(sent.stream);
      expect(bytes.toString("latin1")).toBe(
        Buffer.concat([prefix, FILE, Buffer.from(`\r\n--${out}--\r\n`)]).toString("latin1"),
      );
      expect(sent.size()).toBe(FILE.length);
      expect(sent.sha256()).toBe(createHash("sha256").update(FILE).digest("hex"));
      expect(sent.failure()).toBeNull();
    });
  }

  it("keeps the first of a repeated field and reads a preamble past", async () => {
    const bytes = Buffer.concat([
      Buffer.from("Example preamble\r\n"),
      Buffer.from(
        `--${BOUNDARY}\r\nContent-Disposition: form-data; name="reason"\r\n\r\nExample first reason\r\n`,
      ),
      body({ reason: "Example second reason" }),
    ]);
    const head = await readUploadHead(chunked(bytes, 5), BOUNDARY, 64 * 1024);
    expect(head.fields.get("reason")).toBe("Example first reason");
  });

  it("refuses a form without a file, a nameless part and an unfinished head", async () => {
    await expect(
      readUploadHead(chunked(body(FIELDS, null), 8), BOUNDARY, 64 * 1024),
    ).rejects.toMatchObject({ failure: "malformed" });
    const nameless = Buffer.from(
      `--${BOUNDARY}\r\nContent-Disposition: form-data\r\n\r\nx\r\n--${BOUNDARY}--\r\n`,
    );
    await expect(readUploadHead(chunked(nameless, 8), BOUNDARY, 1024)).rejects.toMatchObject({
      failure: "malformed",
    });
    const cut = body(FIELDS).subarray(0, 60);
    await expect(readUploadHead(chunked(cut, 8), BOUNDARY, 1024)).rejects.toBeInstanceOf(
      UploadFormError,
    );
    await expect(
      readUploadHead(chunked(Buffer.from("no parts at all"), 4), BOUNDARY, 1024),
    ).rejects.toMatchObject({ failure: "malformed" });
    const broken = Buffer.from(`--${BOUNDARY}XX\r\n`);
    await expect(readUploadHead(chunked(broken, 64), BOUNDARY, 1024)).rejects.toMatchObject({
      failure: "malformed",
    });
  });

  it("refuses fields past the allowance, but not a first chunk that carries file bytes", async () => {
    const long = body({ reason: "x".repeat(2000) });
    await expect(readUploadHead(chunked(long, 100), BOUNDARY, 1000)).rejects.toMatchObject({
      failure: "too_large",
    });
    const big = body({ reason: "Example reason for the upload" }, Buffer.alloc(5000, 7));
    const head = await readUploadHead(chunked(big, 6000), BOUNDARY, 1000);
    expect(head.leftover.length).toBeGreaterThan(0);
  });

  it("fails the stream for a file past the limit, a part after it, or a body cut short", async () => {
    const out = newBoundary();
    const tooBig = chunked(body(FIELDS, Buffer.alloc(4000, 1)), 512);
    const big = fileBody(
      await readUploadHead(tooBig, BOUNDARY, 64 * 1024),
      tooBig,
      Buffer.alloc(0),
      out,
      1000,
    );
    await expect(drain(big.stream)).rejects.toBeInstanceOf(UploadFormError);
    expect(big.failure()?.failure).toBe("too_large");
    expect(big.sha256()).toBeNull();

    const after = `--${BOUNDARY}\r\nContent-Disposition: form-data; name="actor_id"\r\n\r\nx\r\n`;
    const extra = chunked(body(FIELDS, FILE, after), 64);
    const sneaky = fileBody(
      await readUploadHead(extra, BOUNDARY, 64 * 1024),
      extra,
      Buffer.alloc(0),
      out,
      4096,
    );
    await expect(drain(sneaky.stream)).rejects.toBeInstanceOf(UploadFormError);
    expect(sneaky.failure()?.failure).toBe("malformed");

    const whole = body(FIELDS);
    const cut = chunked(whole.subarray(0, whole.length - 20), 64);
    const short = fileBody(
      await readUploadHead(cut, BOUNDARY, 64 * 1024),
      cut,
      Buffer.alloc(0),
      out,
      4096,
    );
    await expect(drain(short.stream)).rejects.toBeInstanceOf(UploadFormError);
    expect(short.failure()?.failure).toBe("malformed");
  });

  it("mints a fresh boundary each time", () => {
    expect(newBoundary()).toMatch(/^cw-upload-[0-9a-f]{32}$/);
    expect(newBoundary()).not.toBe(newBoundary());
  });
});
