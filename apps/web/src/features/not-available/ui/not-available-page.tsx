import { NotAvailableYet } from "@compliancewatch/ui";
import type { NotAvailableView } from "@/entities/screen/types";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { renderPreview } from "./previews";

export interface NotAvailablePageProps {
  view: NotAvailableView;
  /** The parent chain of the screen, root first; shown when there is one. */
  crumbs?: readonly Crumb[];
  backHref: string;
}

/** The honest page for a registered screen without its backend: the notice, notes and preview. */
export function NotAvailablePage({ view, crumbs = [], backHref }: NotAvailablePageProps) {
  const preview = renderPreview(view.preview);
  return (
    <div data-slot="not-available-page" className="flex flex-col gap-6">
      <Breadcrumbs crumbs={crumbs} />
      <NotAvailableYet
        title={view.title}
        guideRef={view.guideRef}
        roles={view.roles}
        waitingFor={view.waitingFor}
        backHref={backHref}
      />
      {view.notes ? <p className="max-w-prose text-sm text-fg-muted">{view.notes}</p> : null}
      {preview !== null ? (
        <section aria-label={t("notAvailable.title")} data-slot="preview">
          {preview}
        </section>
      ) : null}
    </div>
  );
}
