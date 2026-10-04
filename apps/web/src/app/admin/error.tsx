"use client";

import { Button, ErrorState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// An unexpected failure in an admin tool renders here, inside the admin shell, so the sidebar
// stays usable. The digest is the reference to quote: it matches onRequestError's log line.
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageHeader title={t("error.title")} />
      <ErrorState
        title={t("error.body")}
        correlationId={error.digest}
        action={
          <Button variant="secondary" onClick={() => reset()}>
            {t("error.retry")}
          </Button>
        }
      />
    </div>
  );
}
