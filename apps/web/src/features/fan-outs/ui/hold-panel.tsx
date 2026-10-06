"use client";

import { useState } from "react";
import { Banner, Button, ErrorState, ReasonDialog } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ControlOutcome } from "./control-outcome";
import { CONTROL_FIELDS, type HoldView, type ReadFailure } from "./controls-shared";
import { useControl, type ControlAction } from "./use-control";

export interface HoldPanelProps {
  /** The hold as the engine reads it, or why it could not be read. */
  hold: { ok: true; hold: HoldView } | { ok: false; failure: ReadFailure };
  /** Only an admin sets or releases the hold. */
  canControl: boolean;
  action: ControlAction;
}

/**
 * The global fan-out hold. While it is set, every page of the fan-out tools leads with a danger
 * banner (the platform's most severe state: no published rule reaches any business) naming who
 * set it, when and why. An admin sets it, or releases it, through a dialog that asks for the
 * reason the engine keeps in its audit log; everyone else reads it.
 */
export function HoldPanel({ hold, canControl, action }: HoldPanelProps) {
  const [open, setOpen] = useState(false);
  const { attempt, send, pending, outcomeRef } = useControl(action);
  if (!hold.ok) {
    return (
      <section
        aria-label={t("fanOuts.hold.heading")}
        data-slot="fan-out-hold"
        className="flex flex-col gap-2"
      >
        <ErrorState
          title={t("fanOuts.hold.failed")}
          detail={hold.failure.message}
          correlationId={hold.failure.correlationId ?? undefined}
        />
      </section>
    );
  }
  const { held, reason, by, since } = hold.hold;
  return (
    <section
      aria-label={t("fanOuts.hold.heading")}
      data-slot="fan-out-hold"
      data-held={held ? "true" : "false"}
      className="flex flex-col gap-3"
    >
      {held ? (
        <Banner
          tone="danger"
          title={t("fanOuts.hold.heldTitle")}
          data-slot="hold-banner"
          action={
            canControl ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={pending}
                aria-busy={pending || undefined}
                onClick={() => setOpen(true)}
              >
                {t("fanOuts.hold.release")}
              </Button>
            ) : null
          }
        >
          <p>{t("fanOuts.hold.heldBody")}</p>
          <p data-slot="hold-reason">
            {reason === null ? t("fanOuts.hold.noReason") : t("fanOuts.hold.reason", { reason })}
          </p>
          {by === null && since === null ? null : (
            <p data-slot="hold-by">
              {t("fanOuts.hold.setBy", {
                by: by ?? t("fanOuts.hold.someone"),
                since: since ?? t("fanOuts.hold.unknownTime"),
              })}
            </p>
          )}
        </Banner>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-fg-muted" data-slot="hold-off">
            {t("fanOuts.hold.off")}
          </p>
          {canControl ? (
            <Button
              type="button"
              size="sm"
              variant="danger"
              disabled={pending}
              aria-busy={pending || undefined}
              onClick={() => setOpen(true)}
            >
              {t("fanOuts.hold.set")}
            </Button>
          ) : null}
        </div>
      )}
      {canControl ? null : (
        <p className="text-xs text-fg-muted" data-slot="hold-admin-only">
          {t("fanOuts.hold.adminOnly")}
        </p>
      )}
      <ControlOutcome attempt={attempt} outcomeRef={outcomeRef} slot="hold-outcome" />
      {open ? (
        <ReasonDialog
          open
          onOpenChange={(next) => {
            if (!next) setOpen(false);
          }}
          title={held ? t("fanOuts.hold.releaseTitle") : t("fanOuts.hold.setTitle")}
          description={
            held ? t("fanOuts.hold.releaseDescription") : t("fanOuts.hold.setDescription")
          }
          label={t("fanOuts.reason")}
          confirmLabel={held ? t("fanOuts.hold.release") : t("fanOuts.hold.set")}
          cancelLabel={t("common.cancel")}
          destructive={!held}
          pending={pending}
          onConfirm={(text) => {
            setOpen(false);
            send(held ? "release" : "hold", {
              [CONTROL_FIELDS.hold]: held ? "off" : "on",
              [CONTROL_FIELDS.reason]: text,
            });
          }}
        />
      ) : null}
    </section>
  );
}
