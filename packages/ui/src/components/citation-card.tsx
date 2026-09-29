import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";
import { Badge } from "./badge";

export interface CitationCardProps extends ComponentProps<"article"> {
  /** The clause text as stored; never paraphrased here. */
  quote: string;
  /** The clause reference as the document numbers it. */
  clauseRef: string;
  documentTitle?: ReactNode;
  documentHref?: string;
  /** True only when a reviewer has checked the quote against the document. */
  verified: boolean;
  verifiedBy?: string;
}

/** A quoted clause with its reference and link, and whether it has been verified. */
export function CitationCard({
  quote,
  clauseRef,
  documentTitle,
  documentHref,
  verified,
  verifiedBy,
  className,
  ...props
}: CitationCardProps) {
  return (
    <article
      data-slot="citation-card"
      data-verified={verified}
      className={cn("flex flex-col gap-2 rounded-md border bg-surface-raised p-4", className)}
      {...props}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium text-fg">{clauseRef}</span>
        {verified ? (
          <Badge tone="success">{verifiedBy ? `Verified by ${verifiedBy}` : "Verified"}</Badge>
        ) : (
          <Badge tone="warning">Not verified</Badge>
        )}
      </div>
      <blockquote className="border-l-4 border-line-strong pl-3 text-sm text-fg">
        {quote}
      </blockquote>
      {documentTitle ? (
        <p className="text-sm text-fg-muted">
          {documentHref ? (
            <a href={documentHref} className="text-primary underline-offset-4 hover:underline">
              {documentTitle}
            </a>
          ) : (
            documentTitle
          )}
        </p>
      ) : null}
    </article>
  );
}
