"use client";

import { useState } from "react";
import { Banner, Button, ReasonDialog } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ControlOutcome } from "./control-outcome";
import { CONTROL_FIELDS, type RollbackState } from "./controls-shared";
import { useControl, type ControlAction } from "./use-control";

export interface RollbackPanelProps {
  rollback: RollbackState;
  /** "example_rule v2", for the dialog. */
  name: string;
  action: ControlAction;
}

/**
 * Rolling a version back is the rulebook's withdraw: the version leaves force today for every
 * tenant, the engine cancels its fan-out if it still runs, and the obligation service closes
 * every open obligation the version made and tells their people. The decisions already made
 * stay, and nothing undoes it: a corrected rule needs a new version through review. The dialog
 * says all of that and asks for the reason the rulebook keeps; only an admin sees the button, and
 * only for a published version, with web.publish_actions on and the review token set.
 */
export function RollbackPanel({ rollback, name, action }: RollbackPanelProps) {
  const [open, setOpen] = useState(false);
  const { attempt, send, pending, outcomeRef } = useControl(action);
  if (rollback.state === "not_admin") {
    return (
      <p className="text-sm text-fg-muted" data-slot="rollback-admin-only">
        {t("fanOut.rollback.adminOnly")}
      </p>
    );
  }
  if (rollback.state === "unknown_version") {
    return (
      <p className="text-sm text-fg-muted" data-slot="rollback-unknown">
        {t("fanOut.rollback.unknownVersion")}
      </p>
    );
  }
  if (rollback.state === "not_published") {
    return (
      <p className="text-sm text-fg-muted" data-slot="rollback-not-published">
        {t("fanOut.rollback.notPublished", { status: rollback.statusLabel })}
      </p>
    );
  }
  const { access } = rollback;
  return (
    <div className="flex flex-col gap-3" data-slot="rollback">
      <Banner tone="warning" title={t("fanOut.rollback.warningTitle")} data-slot="rollback-warning">
        {t("fanOut.rollback.warning")}
      </Banner>
      {access.allowed ? (
        <div>
          <Button
            type="button"
            variant="danger"
            disabled={pending}
            aria-busy={pending || undefined}
            onClick={() => setOpen(true)}
          >
            {t("fanOut.rollback.button")}
          </Button>
        </div>
      ) : (
        <Banner tone="warning" title={access.title} data-slot="rollback-refused">
          {access.detail ?? null}
        </Banner>
      )}
      <ControlOutcome attempt={attempt} outcomeRef={outcomeRef} slot="rollback-outcome" />
      {open ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) setOpen(false);
          }}
          title={t("fanOut.rollback.title", { name })}
          description={t("fanOut.rollback.description")}
          label={t("fanOuts.reason")}
          confirmLabel={t("fanOut.rollback.confirm")}
          cancelLabel={t("common.cancel")}
          destructive
          pending={pending}
          onConfirm={(reason) => {
            setOpen(false);
            send("rollback", { [CONTROL_FIELDS.reason]: reason });
          }}
        />
      ) : null}
    </div>
  );
}
