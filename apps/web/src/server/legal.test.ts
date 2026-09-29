import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { LEGAL_DOC_NAMES } from "@/shared/config/legal-docs";
import {
  containsRawHtml,
  extractTitle,
  extractVersion,
  legalDir,
  readLegalDocument,
  readLegalDocuments,
  readLegalVersions,
  renderLegalMarkdown,
} from "./legal";

const REPO_ROOT = resolve(__dirname, "../../../..");

describe("legalDir", () => {
  it("finds docs/legal from apps/web and from the repo root, and fails elsewhere", () => {
    const expected = resolve(REPO_ROOT, "docs/legal");
    expect(legalDir(resolve(REPO_ROOT, "apps/web"))).toBe(expected);
    expect(legalDir(REPO_ROOT)).toBe(expected);
    expect(() => legalDir(resolve(REPO_ROOT, "apps"))).toThrow(/docs\/legal not found/);
  });
});

describe("extraction", () => {
  it("reads the Version line and the first heading", () => {
    const source = "# Privacy notice\n\n> Draft.\n\nVersion: 0.1-draft\nEffective: [not yet]\n";
    expect(extractVersion(source)).toBe("0.1-draft");
    expect(extractTitle(source)).toBe("Privacy notice");
    expect(() => extractVersion("# Title\n")).toThrow(/no Version line/);
    expect(() => extractTitle("Version: 1.0\n")).toThrow(/no heading/);
  });

  it("detects raw HTML tags in markdown source", () => {
    expect(containsRawHtml("plain *markdown* with a < sign and 1 > 0")).toBe(false);
    expect(containsRawHtml("text <script>alert(1)</script>")).toBe(true);
    expect(containsRawHtml("<br/>")).toBe(true);
  });

  it("renders markdown to HTML with marked's defaults", () => {
    const html = renderLegalMarkdown("# Title\n\nA paragraph with **bold** text.\n\n- item\n");
    expect(html).toContain("<h1>Title</h1>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<li>item</li>");
  });
});

describe("docs/legal", () => {
  it("contains no raw HTML tag in any published document, so the rendered pages carry only markdown", () => {
    // Only the documents the app renders are checked. The internal notes in the same folder
    // (consent-record.md, data-map.md) use angle-bracket placeholders in their tables.
    const dir = legalDir(REPO_ROOT);
    const files = readdirSync(dir).filter((name) => name.endsWith(".md"));
    expect(files.length).toBeGreaterThanOrEqual(LEGAL_DOC_NAMES.length);
    for (const name of LEGAL_DOC_NAMES) {
      const file = `${name}.md`;
      expect(files).toContain(file);
      expect(containsRawHtml(readFileSync(join(dir, file), "utf8")), file).toBe(false);
    }
  });

  it("renders every published document as a draft with its heading and version", () => {
    const documents = readLegalDocuments(legalDir(REPO_ROOT));
    expect(documents.map((doc) => doc.name)).toEqual(LEGAL_DOC_NAMES);
    for (const doc of documents) {
      expect(doc.version, doc.name).toMatch(/^\d+\.\d+(\.\d+)?(-draft)?$/);
      expect(doc.isDraft, doc.name).toBe(true);
      expect(doc.title.length, doc.name).toBeGreaterThan(0);
      expect(doc.html, doc.name).toContain(`<h1>${doc.title}</h1>`);
    }
    expect(readLegalDocument("privacy-notice", legalDir(REPO_ROOT)).title).toBe("Privacy notice");
  });

  it("reads every published document's heading and version without rendering it", () => {
    const versions = readLegalVersions(legalDir(REPO_ROOT));
    const documents = readLegalDocuments(legalDir(REPO_ROOT));
    expect(Object.keys(versions)).toEqual(LEGAL_DOC_NAMES);
    for (const doc of documents) {
      expect(versions[doc.name]).toEqual({
        name: doc.name,
        title: doc.title,
        version: doc.version,
        isDraft: doc.isDraft,
      });
    }
  });

  it("fails on a document that is not there", () => {
    expect(() => readLegalDocument("privacy-notice", resolve(REPO_ROOT, "apps"))).toThrow();
  });
});
