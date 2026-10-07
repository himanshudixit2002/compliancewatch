"use client";

import { Button } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import type { WriteResult } from "./form-shared";
import { WriteResultView } from "./write-result";

export interface SeedTasksButtonProps {
  action: WriteAction<WriteResult>;
}

/**
 * Opens a review task for every seed draft that needs review and has none waiting. The rulebook
 * opens nothing twice, so pressing it again says that every draft already has a task.
 */
export function SeedTasksButton({ action }: SeedTasksButtonProps) {
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  return (
    <div className="flex flex-col gap-2" data-slot="seed-tasks">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(new FormData(event.currentTarget));
        }}
        className="flex flex-wrap items-center gap-3"
      >
        <Button
          type="submit"
          variant="secondary"
          disabled={pending}
          aria-busy={pending || undefined}
        >
          {t("reviewQueue.seed.button")}
        </Button>
        <p className="max-w-prose text-sm text-fg-muted">{t("reviewQueue.seed.help")}</p>
      </form>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="seed-tasks-outcome"
        renderValue={(value) => <WriteResultView result={value} />}
      />
    </div>
  );
}
