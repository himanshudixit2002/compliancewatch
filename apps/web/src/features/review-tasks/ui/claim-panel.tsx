"use client";

import { Button } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { WriteOutcome, useWriteAction, type WriteAction } from "@/shared/ui/write-outcome";
import type { ClaimView, WriteResult } from "./form-shared";
import { PersonName, WriteResultView } from "./write-result";

export interface ClaimPanelProps {
  action: WriteAction<WriteResult>;
  claim: ClaimView;
}

/**
 * Who holds the task. A task is claimed before a version is drafted or edited, and only its
 * claimant drafts and edits; claiming one's own task again changes nothing. Someone else's claim
 * stands until a decision. The panel stays after the claim, so its answer is still there.
 */
export function ClaimPanel({ action, claim }: ClaimPanelProps) {
  const { attempt, send, pending, outcomeRef } = useWriteAction(action);
  return (
    <section
      aria-label={t("workbench.claim.region")}
      data-slot="claim-panel"
      data-claim={claim.state}
      className="flex flex-col gap-2"
    >
      {claim.state === "open" ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-fg">{t("workbench.claim.open")}</p>
          {claim.canClaim ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                send(new FormData(event.currentTarget));
              }}
            >
              <Button type="submit" disabled={pending} aria-busy={pending || undefined}>
                {t("workbench.claim.button")}
              </Button>
            </form>
          ) : null}
        </div>
      ) : claim.state === "mine" ? (
        <p className="text-sm text-fg">
          {claim.at === null
            ? t("workbench.claim.mine")
            : t("workbench.claim.mineAt", { at: claim.at })}
        </p>
      ) : claim.state === "other" ? (
        <p className="text-sm text-fg">
          {t("workbench.claim.otherLead")} <PersonName person={claim.by} />
          {claim.at === null ? null : ` ${t("workbench.claim.on", { at: claim.at })}`}.{" "}
          {t("workbench.claim.otherTail")}
        </p>
      ) : (
        <p className="text-sm text-fg-muted">{t("workbench.claim.decided")}</p>
      )}
      <WriteOutcome
        attempt={attempt}
        pending={pending}
        onResend={send}
        outcomeRef={outcomeRef}
        slot="claim-outcome"
        renderValue={(value) => <WriteResultView result={value} />}
      />
    </section>
  );
}
