import { DraftBanner } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface LegalDocumentProps {
  /** The document's first heading, for the printed footer. */
  title: string;
  /** The `Version:` value from the markdown. */
  version: string;
  /** True while the version ends in -draft. */
  isDraft: boolean;
  /** HTML rendered from the repository's markdown by server/legal.ts (no raw HTML in source). */
  html: string;
}

const ARTICLE_STYLES = [
  "max-w-prose text-fg print:max-w-none",
  "[&_h1]:text-3xl [&_h1]:font-semibold [&_h1]:tracking-tight",
  "[&_h2]:mt-8 [&_h2]:text-xl [&_h2]:font-semibold",
  "[&_h3]:mt-6 [&_h3]:text-lg [&_h3]:font-semibold",
  "[&_p]:my-3 [&_p]:leading-relaxed",
  "[&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6",
  "[&_li]:my-1",
  "[&_blockquote]:my-3 [&_blockquote]:border-l-4 [&_blockquote]:border-line-strong [&_blockquote]:pl-3 [&_blockquote]:text-fg-muted",
  "[&_a]:text-primary [&_a]:underline",
  "[&_table]:my-3 [&_table]:w-full [&_table]:text-sm [&_th]:border-b [&_th]:p-2 [&_th]:text-left [&_td]:border-b [&_td]:p-2 [&_td]:align-top",
  "[&_code]:rounded-sm [&_code]:bg-surface [&_code]:px-1 [&_code]:font-mono [&_code]:text-sm",
].join(" ");

/**
 * A legal document: the draft banner above it while its version ends in -draft (a plain version
 * line once it is reviewed), the document's own heading as the page's h1, and a line that shows
 * only on paper naming the document and its version. The print stylesheet in globals.css leaves
 * out the shell and keeps the banner, so a printed draft still says it is one.
 */
export function LegalDocument({ title, version, isDraft, html }: LegalDocumentProps) {
  return (
    <div data-slot="legal-document" className="flex flex-col gap-6">
      {isDraft ? (
        <DraftBanner version={version} />
      ) : (
        <p data-slot="legal-version" className="text-sm text-fg-muted">
          {t("common.version", { version })}
        </p>
      )}
      <article className={ARTICLE_STYLES} dangerouslySetInnerHTML={{ __html: html }} />
      <p data-slot="legal-printed" className="hidden text-sm text-fg-muted print:block">
        {t("legal.printed", { title, version })}
      </p>
    </div>
  );
}
