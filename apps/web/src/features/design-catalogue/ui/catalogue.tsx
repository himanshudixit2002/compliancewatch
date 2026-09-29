"use client";

import { PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ButtonsSection } from "./sections/buttons";
import { CalendarSection } from "./sections/calendar";
import { ContentSection } from "./sections/content";
import { FeedbackSection } from "./sections/feedback";
import { FormsSection } from "./sections/forms";
import { StatesSection } from "./sections/states";
import { SurfacesSection } from "./sections/surfaces";
import { TablesSection } from "./sections/tables";
import { TokensSection } from "./sections/tokens";
import { ThemeToggle } from "./theme-toggle";

/** The group ids in page order; the e2e suite checks each one. */
export const CATALOGUE_SECTIONS = [
  "tokens",
  "buttons",
  "forms",
  "feedback",
  "surfaces",
  "tables",
  "calendar",
  "content",
  "states",
] as const;

/**
 * Every component of the UI kit in its states, with synthetic example data. The shells and
 * PageHeader are not repeated inside: the page itself already renders them once.
 */
export function Catalogue() {
  return (
    <div data-slot="design-catalogue" className="flex flex-col gap-8">
      <PageHeader
        title={t("design.title")}
        description={t("design.intro")}
        actions={<ThemeToggle />}
      />
      <nav aria-label={t("design.title")} className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        {CATALOGUE_SECTIONS.map((id) => (
          <a key={id} href={`#catalogue-${id}`} className="text-primary hover:underline">
            {id}
          </a>
        ))}
      </nav>
      <TokensSection />
      <ButtonsSection />
      <FormsSection />
      <FeedbackSection />
      <SurfacesSection />
      <TablesSection />
      <CalendarSection />
      <ContentSection />
      <StatesSection />
    </div>
  );
}
