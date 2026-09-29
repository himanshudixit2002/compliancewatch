import type { Route } from "next";
import Link from "next/link";
import { Banner, DRAFT_BANNER_TEXT, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { OnboardingStepper, type OnboardingStepId } from "./onboarding-stepper";

/** A required document that is still a draft, as the closed notice names it. */
export interface ClosedDocument {
  name: string;
  title: string;
  version: string;
}

export interface OnboardingClosedProps {
  /** The step's own title, kept as the page's h1. */
  title: string;
  step: Extract<OnboardingStepId, "consent" | "business">;
  /** The required documents that are drafts. */
  documents: readonly ClosedDocument[];
  /** The page of a legal document, by its docs/legal name. */
  documentHref: (name: string) => string;
}

/**
 * What the consent step and the business step show in production while a required legal
 * document is a draft: no form, the draft banner, and each draft with its version, linked to
 * its page. Shared by the two steps, which live in features that may not import each other.
 */
export function OnboardingClosed({ title, step, documents, documentHref }: OnboardingClosedProps) {
  return (
    <div data-slot="onboarding-closed" className="flex max-w-3xl flex-col gap-6">
      <OnboardingStepper current={step} />
      <PageHeader title={title} description={t("onboardingClosed.intro")} />
      <Banner tone="warning" title={DRAFT_BANNER_TEXT} data-slot="draft-banner">
        <p>{t("onboardingClosed.body")}</p>
        <ul className="mt-2 list-disc pl-5">
          {documents.map((document) => (
            <li key={document.name}>
              <Link href={documentHref(document.name) as Route}>
                {t("onboardingClosed.document", {
                  title: document.title,
                  version: document.version,
                })}
              </Link>
            </li>
          ))}
        </ul>
      </Banner>
      <p className="text-sm text-fg-muted">{t("onboardingClosed.nothingRecorded")}</p>
    </div>
  );
}
