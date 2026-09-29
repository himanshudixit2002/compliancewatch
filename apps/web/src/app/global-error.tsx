"use client";

import { Button, ErrorState } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import "./globals.css";

// Replaces the root layout when it fails, so it carries its own html, body and styles.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg font-sans text-fg antialiased">
        <main className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
          <h1 className="text-2xl font-semibold">{t("error.globalTitle")}</h1>
          <ErrorState
            title={t("error.body")}
            correlationId={error.digest}
            action={
              <Button variant="secondary" onClick={() => reset()}>
                {t("error.retry")}
              </Button>
            }
          />
        </main>
      </body>
    </html>
  );
}
