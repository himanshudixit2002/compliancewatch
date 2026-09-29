"use client";

import { Button, ErrorState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

// Error boundaries are client components; this one renders inside the segment's shell.
// The digest is the reference to quote: it matches the JSON line onRequestError wrote.
export default function ErrorPage({
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
