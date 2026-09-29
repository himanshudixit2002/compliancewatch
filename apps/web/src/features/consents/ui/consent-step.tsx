import type { Route } from "next";
import Link from "next/link";
import { Banner, Button, DRAFT_BANNER_TEXT, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { OnboardingStepper } from "@/shared/ui/onboarding-stepper";
import type { ConsentStepView } from "../model/consent-step";
import { ConsentForm, type ConsentAction } from "./consent-form";

export interface ConsentStepProps {
  title: string;
  view: ConsentStepView;
  action: ConsentAction;
  /** Where the flow goes on: the business step. */
  continueHref: string;
  /** The page of a legal document, by its docs/legal name. */
  documentHref: (name: string) => string;
  /** The form field of the WhatsApp number. */
  whatsappField: string;
  /** The consents settings page, where an optional purpose is withdrawn; null without access. */
  settingsHref: string | null;
}

/**
 * The first onboarding step. With every required purpose already granted at the current
 * versions it shows what was agreed, when, and a way on; otherwise the form. While a document
 * it refers to is a draft, the draft banner names each one with its version, since that is what
 * a record will carry.
 */
export function ConsentStep({
  title,
  view,
  action,
  continueHref,
  documentHref,
  whatsappField,
  settingsHref,
}: ConsentStepProps) {
  return (
    <div data-slot="consent-step" className="flex max-w-3xl flex-col gap-6">
      <OnboardingStepper current="consent" />
      <PageHeader title={title} description={t("consent.intro")} />
      {view.drafts.length > 0 ? (
        <Banner tone="warning" title={DRAFT_BANNER_TEXT} data-slot="draft-banner">
          {t("consent.draft", {
            documents: view.drafts
              .map((document) => `${document.title} ${document.version}`)
              .join(", "),
          })}
        </Banner>
      ) : null}
      {view.accepted ? (
        <section data-slot="consent-accepted" className="flex flex-col gap-4">
          <Banner tone="success" title={t("consent.accepted.title")}>
            <ul className="list-disc pl-5">
              {view.acceptedPurposes.map((item) => (
                <li key={item.purpose}>
                  {t("consent.accepted.item", {
                    purpose: item.label,
                    notice: item.noticeVersion,
                    date: item.recordedAt,
                  })}
                </li>
              ))}
            </ul>
          </Banner>
          <p className="text-sm text-fg-muted">{t("consent.appendOnly")}</p>
          <div>
            <Button asChild>
              <Link href={continueHref as Route}>{t("consent.continue")}</Link>
            </Button>
          </div>
        </section>
      ) : (
        <ConsentForm
          action={action}
          offerWhatsapp={view.offerWhatsapp}
          whatsappField={whatsappField}
          settingsHref={settingsHref}
          options={view.options.map((option) => ({
            purpose: option.purpose,
            label: option.label,
            required: option.required,
            document: { title: option.document.title, version: option.document.version },
            documentHref: documentHref(option.document.name),
            grantedAt: option.grantedAt,
          }))}
        />
      )}
    </div>
  );
}
