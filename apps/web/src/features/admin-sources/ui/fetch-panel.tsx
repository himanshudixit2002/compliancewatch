"use client";

import { useId, useState } from "react";
import { Button, ReasonDialog } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import { FETCH_FIELDS, REASON_MIN_LENGTH, type FetchResult } from "./source-shared";

export interface FetchPanelProps {
  /** The fetch action, bound to the source. */
  action: WriteAction<FetchResult>;
  /** The crawl switch's name and variable, which the panel names. */
  flag: { name: string; variable: string };
}

/**
 * "Fetch now": a crawl of the source started by hand, with the reason the pipeline keeps. The
 * panel says up front what the pipeline does with it: while crawling is off (the flag, off by
 * default) it starts nothing and reads no regulator site, and says so; with crawling on it
 * records a run and lists the source, a paused one included.
 */
export function FetchPanel({ action, flag }: FetchPanelProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  return (
    <section
      aria-labelledby={`${id}-heading`}
      data-slot="fetch-panel"
      className="flex flex-col gap-3"
    >
      <h2 id={`${id}-heading`} className="text-lg font-semibold text-fg">
        {t("adminSources.fetch.title")}
      </h2>
      <p className="max-w-prose text-sm text-fg-muted">
        {t("adminSources.fetch.intro", { flag: flag.name, variable: flag.variable })}
      </p>
      <div>
        <Button
          type="button"
          variant="secondary"
          disabled={pending}
          aria-busy={pending || undefined}
          onClick={() => setOpen(true)}
        >
          {t("adminSources.fetch.button")}
        </Button>
      </div>
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="fetch-outcome"
      />
      {open ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) setOpen(false);
          }}
          title={t("adminSources.fetch.dialogTitle")}
          description={t("adminSources.fetch.dialogBody", { flag: flag.name })}
          label={t("adminSources.reason")}
          hint={t("adminSources.reasonHelp", { min: REASON_MIN_LENGTH })}
          confirmLabel={t("adminSources.fetch.button")}
          cancelLabel={t("common.cancel")}
          pending={pending}
          onConfirm={(reason) => {
            setOpen(false);
            const formData = new FormData();
            formData.set(FETCH_FIELDS.reason, reason);
            send(formData);
          }}
        />
      ) : null}
    </section>
  );
}
