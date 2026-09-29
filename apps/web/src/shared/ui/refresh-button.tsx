"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface RefreshButtonProps {
  className?: string;
}

/**
 * Renders the page again on the server (router.refresh) without a full reload: the counts, the
 * probes and every other read of a dynamic page are fetched again. Busy while it runs.
 */
export function RefreshButton({ className }: RefreshButtonProps) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <Button
      type="button"
      variant="secondary"
      className={className}
      disabled={pending}
      aria-busy={pending || undefined}
      onClick={() => startTransition(() => router.refresh())}
    >
      {pending ? t("common.refreshing") : t("common.refresh")}
    </Button>
  );
}
