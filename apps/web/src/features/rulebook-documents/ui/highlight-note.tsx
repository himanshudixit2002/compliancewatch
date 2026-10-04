import { Banner } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { HighlightOutcome } from "../model/document-view";

export interface HighlightNoteProps {
  highlight: HighlightOutcome;
}

/** Says what the link marked, or why it marked less than it asked for. */
export function HighlightNote({ highlight }: HighlightNoteProps) {
  switch (highlight.kind) {
    case "none":
      return null;
    case "span":
      return (
        <Banner tone="info" data-slot="highlight-note" data-kind={highlight.kind}>
          {t("documents.highlight.span", {
            ref: highlight.clauseRef,
            start: highlight.start,
            end: highlight.end,
          })}
        </Banner>
      );
    case "clause":
      return (
        <Banner tone="info" data-slot="highlight-note" data-kind={highlight.kind}>
          {t("documents.highlight.clause", { ref: highlight.clauseRef })}
        </Banner>
      );
    case "fallback":
      return (
        <Banner
          tone="warning"
          title={t("documents.highlight.fallbackTitle")}
          data-slot="highlight-note"
          data-kind={highlight.kind}
        >
          {t("documents.highlight.fallback", {
            ref: highlight.clauseRef,
            start: highlight.start,
            end: highlight.end,
          })}
        </Banner>
      );
    case "missing":
      return (
        <Banner
          tone="warning"
          title={t("documents.highlight.missingTitle")}
          data-slot="highlight-note"
          data-kind={highlight.kind}
        >
          {t("documents.highlight.missing", { clauseId: highlight.clauseId })}
        </Banner>
      );
    case "invalid":
      return (
        <Banner
          tone="warning"
          title={t("documents.highlight.invalidTitle")}
          data-slot="highlight-note"
          data-kind={highlight.kind}
        >
          {t("documents.highlight.invalid")}
        </Banner>
      );
  }
}
