import type { Route } from "next";
import Link from "next/link";
import { PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ScreenStatusChip } from "@/shared/ui/screen-status-chip";
import type { SettingsCard, SettingsIndexView } from "../model/cards";

export interface SettingsIndexProps {
  title: string;
  view: SettingsIndexView;
}

function CardList({ id, heading, cards }: { id: string; heading: string; cards: SettingsCard[] }) {
  if (cards.length === 0) return null;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold text-fg">
        {heading}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {cards.map((card) => (
          <li
            key={card.id}
            data-screen={card.id}
            className="flex flex-col gap-1 rounded-md border border-line bg-surface p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link
                href={card.href as Route}
                className="font-medium text-primary underline-offset-2 hover:underline"
              >
                {card.title}
              </Link>
              <ScreenStatusChip status={card.status} />
            </div>
            {card.description === "" ? null : (
              <p className="text-sm text-fg-muted">{card.description}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The settings index: the settings pages, then the account pages, each with its status. */
export function SettingsIndex({ title, view }: SettingsIndexProps) {
  return (
    <div data-slot="settings-index" className="flex max-w-4xl flex-col gap-8">
      <PageHeader title={title} description={t("settings.intro")} />
      <CardList id="settings-pages" heading={t("settings.pagesTitle")} cards={view.settings} />
      <CardList id="settings-account" heading={t("settings.accountTitle")} cards={view.account} />
    </div>
  );
}
