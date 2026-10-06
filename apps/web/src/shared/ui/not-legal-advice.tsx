import type { Route } from "next";
import Link from "next/link";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

export interface NotLegalAdviceProps {
  className?: string;
}

/**
 * The footer of every page that tells a business what applies to it, when it is due or what a
 * rule says: the service is not legal, tax or accounting advice (section 2 of the terms), rules
 * are extracted by software and can be wrong, and the cited sources are what to check.
 */
export function NotLegalAdvice({ className }: NotLegalAdviceProps) {
  const terms = hrefFor(screenById("system.legal"), { doc: "terms-of-service" });
  return (
    <aside
      aria-label={t("notLegalAdvice.label")}
      data-slot="not-legal-advice"
      className={className ?? "border-t border-line pt-4 text-xs text-fg-muted"}
    >
      <p className="max-w-prose">
        {t("notLegalAdvice.text")}{" "}
        <Link href={terms as Route} className="text-primary underline underline-offset-2">
          {t("notLegalAdvice.terms")}
        </Link>
      </p>
    </aside>
  );
}
