import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
  KeyValue,
  ProgressBar,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ScreenStatusChip, type ScreenStatus } from "@/shared/ui/screen-status-chip";
import type { BusinessHomeView } from "../model/business-pages";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";

export interface BusinessHomeLinks {
  profile: string;
  attributes: string;
  snapshot: string;
  reviewTasks: string;
  /** The questions step, or null for a role that does not onboard (a compliance lead). */
  questions: string | null;
  done: string | null;
  /**
   * The business step, for another business (another PAN), or null for a role that does not add
   * one. The businesses list sends an owner with one business straight here, so this is the way
   * to a second one; another GSTIN of this business is added on the profile page.
   */
  addBusiness: string | null;
}

/** A registry screen of this business that is not built yet, with its notice page. */
export interface LaterScreen {
  id: string;
  title: string;
  status: ScreenStatus;
  href: string;
}

export interface BusinessHomeProps {
  view: BusinessHomeView;
  header: Omit<BusinessPageHeaderProps, "title" | "description">;
  links: BusinessHomeLinks;
  later: readonly LaterScreen[];
  /** True for a CA firm, whose businesses are its clients. */
  clients?: boolean;
}

function Tile({ title, body, href }: { title: string; body: string; href: string }) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle>
          <Link href={href as Route} className="text-primary underline">
            {title}
          </Link>
        </CardTitle>
        <CardDescription>{body}</CardDescription>
      </CardHeader>
    </Card>
  );
}

/**
 * A business's home: its identifiers and registrations, how far onboarding has got, a tile per
 * profile page, and the screens for this business that are not built yet, each with its status.
 */
export function BusinessHome({ view, header, links, later, clients = false }: BusinessHomeProps) {
  const { header: business, progress, counts } = view;
  return (
    <div data-slot="business-home" className="flex max-w-4xl flex-col gap-6">
      <BusinessPageHeader
        {...header}
        title={business.name}
        description={t("business.homeIntro", { pan: business.pan })}
        actions={
          links.addBusiness === null ? undefined : (
            <Button asChild variant="secondary">
              <Link href={links.addBusiness as Route}>
                {clients ? t("business.addClient") : t("business.addBusiness")}
              </Link>
            </Button>
          )
        }
      />
      <KeyValue
        items={[
          { key: "pan", label: t("prefill.pan"), value: business.pan },
          {
            key: "registrations",
            label: t("business.registrations"),
            value:
              business.registrations.length === 0 ? (
                t("business.noRegistrations")
              ) : (
                <ul>
                  {business.registrations.map((node) => (
                    <li key={node.id}>
                      {node.key} ({node.name})
                    </li>
                  ))}
                </ul>
              ),
          },
          { key: "version", label: t("business.version"), value: String(business.version) },
          { key: "updated", label: t("business.updatedAt"), value: business.updatedAt },
        ]}
      />
      <section aria-labelledby="business-onboarding" className="flex flex-col gap-3">
        <h2 id="business-onboarding" className="text-lg font-semibold text-fg">
          {t("business.onboardingTitle")}
        </h2>
        <ProgressBar
          label={t("question.progressLabel", { name: business.name })}
          value={progress.answered}
          max={progress.total}
          valueText={progress.text}
        />
        {progress.complete ? (
          <p className="text-sm text-fg-muted">{t("business.onboardingComplete")}</p>
        ) : null}
        {links.questions !== null && links.done !== null ? (
          <div>
            <Button asChild variant="secondary" size="sm">
              <Link href={(progress.complete ? links.done : links.questions) as Route}>
                {progress.complete ? t("business.toSummary") : t("business.toQuestions")}
              </Link>
            </Button>
          </div>
        ) : null}
      </section>
      <section aria-labelledby="business-pages" className="flex flex-col gap-3">
        <h2 id="business-pages" className="text-lg font-semibold text-fg">
          {t("business.pagesTitle")}
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Tile
            title={t("business.tile.profile")}
            body={t("business.tile.profileBody", { count: business.registrations.length })}
            href={links.profile}
          />
          <Tile
            title={t("business.tile.attributes")}
            body={t("business.tile.attributesBody", {
              known: counts.known,
              unsure: counts.unsure,
              notApplicable: counts.not_applicable,
            })}
            href={links.attributes}
          />
          <Tile
            title={t("business.tile.snapshot")}
            body={t("business.tile.snapshotBody")}
            href={links.snapshot}
          />
          <Tile
            title={t("business.tile.reviewTasks")}
            body={t("business.tile.reviewTasksBody", { count: view.openTasks })}
            href={links.reviewTasks}
          />
        </div>
      </section>
      {later.length > 0 ? (
        <section aria-labelledby="business-later" className="flex flex-col gap-3">
          <h2 id="business-later" className="text-lg font-semibold text-fg">
            {t("business.laterTitle")}
          </h2>
          <ul className="flex flex-col gap-2">
            {later.map((screen) => (
              <li key={screen.id} className="flex flex-wrap items-center gap-2 text-sm">
                <Link href={screen.href as Route} className="text-primary underline">
                  {screen.title}
                </Link>
                <ScreenStatusChip status={screen.status} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
