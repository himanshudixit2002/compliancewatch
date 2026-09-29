import "server-only";

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { marked } from "marked";
import {
  LEGAL_DOC_NAMES,
  REQUIRED_LEGAL_DOCS,
  type LegalDocName,
} from "@/shared/config/legal-docs";
import { webEnvName, type WebEnvName } from "./env";

/**
 * Reads the legal drafts in docs/legal at build time and renders them to HTML with marked's
 * defaults. marked does not sanitise; the directory is repository-owned and legal.test.ts
 * asserts that none of its files contains a raw HTML tag, so nothing but the markdown's own
 * structure reaches the page.
 */
export interface LegalDocument {
  name: LegalDocName;
  /** The document's first heading. */
  title: string;
  /** The `Version:` line, for example "0.1-draft"; a consent records this value. */
  version: string;
  /** True while the version ends in -draft. */
  isDraft: boolean;
  html: string;
}

const VERSION_LINE = /^Version:[ \t]*(\S+)[ \t]*$/m;
const TITLE_LINE = /^#[ \t]+(.+?)[ \t]*$/m;
const RAW_HTML_TAG = /<\/?[a-zA-Z][^<>]*>/;

/** docs/legal, whether the process runs from apps/web (next build, next start) or the repo root. */
export function legalDir(cwd: string = process.cwd()): string {
  const candidates = [resolve(cwd, "docs/legal"), resolve(cwd, "../../docs/legal")];
  const found = candidates.find((dir) => existsSync(join(dir, "README.md")));
  if (found === undefined) {
    throw new Error(`docs/legal not found from ${cwd} (tried ${candidates.join(", ")})`);
  }
  return found;
}

export function extractVersion(markdown: string): string {
  const match = VERSION_LINE.exec(markdown);
  if (match === null) throw new Error("legal document has no Version line");
  return match[1] as string;
}

export function extractTitle(markdown: string): string {
  const match = TITLE_LINE.exec(markdown);
  if (match === null) throw new Error("legal document has no heading");
  return match[1] as string;
}

/** True when the markdown source itself contains an HTML tag; the drafts must not. */
export function containsRawHtml(markdown: string): boolean {
  return RAW_HTML_TAG.test(markdown);
}

export function renderLegalMarkdown(markdown: string): string {
  return marked.parse(markdown, { async: false, gfm: true });
}

export function readLegalDocument(name: LegalDocName, dir: string = legalDir()): LegalDocument {
  const markdown = readFileSync(join(dir, `${name}.md`), "utf8");
  const version = extractVersion(markdown);
  return {
    name,
    title: extractTitle(markdown),
    version,
    isDraft: version.endsWith("-draft"),
    html: renderLegalMarkdown(markdown),
  };
}

export function readLegalDocuments(dir: string = legalDir()): LegalDocument[] {
  return LEGAL_DOC_NAMES.map((name) => readLegalDocument(name, dir));
}

/** A document's heading and Version line without rendering it: what a consent records. */
export interface LegalVersion {
  name: LegalDocName;
  title: string;
  version: string;
  isDraft: boolean;
}

/**
 * Every published document's version, read from docs/legal on each call (three small files) so
 * a page shows, and a consent records, the version the running build ships.
 */
export function readLegalVersions(dir: string = legalDir()): Record<LegalDocName, LegalVersion> {
  const versions = {} as Record<LegalDocName, LegalVersion>;
  for (const name of LEGAL_DOC_NAMES) {
    const markdown = readFileSync(join(dir, `${name}.md`), "utf8");
    const version = extractVersion(markdown);
    versions[name] = {
      name,
      title: extractTitle(markdown),
      version,
      isDraft: version.endsWith("-draft"),
    };
  }
  return versions;
}

/** Whether a new customer may agree to the documents and add a business in this deployment. */
export interface OnboardingGate {
  /** True in production while a required document is a draft: nothing may be agreed to yet. */
  closed: boolean;
  /** The required documents that are still drafts, in docs/legal order. */
  drafts: LegalVersion[];
}

export interface OnboardingGateOptions {
  /** CW_WEB_ENV; read from the environment by default. */
  env?: WebEnvName;
  /** The documents' Version lines; read from docs/legal by default. */
  versions?: Readonly<Record<LegalDocName, LegalVersion>>;
}

/**
 * Production onboarding stays closed while any required document (REQUIRED_LEGAL_DOCS: the
 * terms and the privacy notice) has a Version line ending in -draft: nobody agrees to a draft in
 * production. Local, test and staging stay open, with the draft banner naming each draft and its
 * version, so the flow can be built, tested and reviewed before a lawyer has approved the
 * wording.
 */
export function onboardingGate(options: OnboardingGateOptions = {}): OnboardingGate {
  const versions = options.versions ?? readLegalVersions();
  const env = options.env ?? webEnvName();
  const drafts = LEGAL_DOC_NAMES.filter((name) => REQUIRED_LEGAL_DOCS.includes(name))
    .map((name) => versions[name])
    .filter((document) => document.isDraft);
  return { closed: env === "prod" && drafts.length > 0, drafts };
}
