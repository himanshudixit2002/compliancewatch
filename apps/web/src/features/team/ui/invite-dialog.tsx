"use client";

import type { Route } from "next";
import Link from "next/link";
import { useActionState, useId, useState } from "react";
import {
  Banner,
  Button,
  CheckboxGroup,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  ErrorState,
  Field,
  Input,
  toast,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";

export type TeamAction = (state: ActionState, formData: FormData) => Promise<ActionState>;

export interface TeamRoleOption {
  value: string;
  label: string;
  needsMfa: boolean;
}

export interface TeamFormFields {
  screen: string;
  userId: string;
  contact: string;
  displayName: string;
  roles: string;
  reason: string;
}

export interface InviteDialogProps {
  action: TeamAction;
  screenId: string;
  fields: TeamFormFields;
  roles: readonly TeamRoleOption[];
  /** The billing page, linked from a seat-limit refusal; null where there is none. */
  billingHref: string | null;
}

/** True when the problem is identity's 402: the plan has no seat left. */
export function isSeatLimit(problemType: string | undefined): boolean {
  return problemType?.endsWith(":identity-seat-limit-reached") ?? false;
}

/**
 * The invite dialog: one contact (an email address or a mobile number), the person's name and
 * the roles the tenant's kind allows, each marked when it signs in with a second factor. A
 * refused invitation keeps the dialog open with identity's words (a role the kind lacks on the
 * roles, a taken address on the contact, the plan's seat limit with the way to billing); an
 * accepted one closes it and the page lists the member.
 */
export function InviteDialog({ action, screenId, fields, roles, billingHref }: InviteDialogProps) {
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState(
    async (previous: ActionState, formData: FormData): Promise<ActionState> => {
      const next = await action(previous, formData);
      if (next.status === "ok") {
        setOpen(false);
        if (next.message) toast.success(next.message);
      }
      return next;
    },
    idleAction(),
  );
  const id = useId();
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-slot="invite-open">
          {t("team.invite")}
        </Button>
      </DialogTrigger>
      <DialogContent data-slot="invite-dialog">
        <form action={formAction} className="flex flex-col gap-5" data-slot="invite-form">
          <DialogHeader>
            <DialogTitle>{t("team.inviteTitle")}</DialogTitle>
            <DialogDescription>{t("team.inviteBody")}</DialogDescription>
          </DialogHeader>
          <input type="hidden" name={fields.screen} value={screenId} />
          {problem ? (
            <ErrorState
              title={problem.title}
              detail={problem.detail}
              correlationId={problem.correlationId || undefined}
              action={
                isSeatLimit(problem.type) && billingHref !== null ? (
                  <Button asChild variant="secondary" size="sm">
                    <Link href={billingHref as Route} data-slot="seat-limit-billing">
                      {t("team.error.seatLimitBilling")}
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          ) : null}
          {formErrors.length > 0 ? (
            <Banner tone="danger" title={t("team.refused")}>
              <ul>
                {formErrors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          <Field
            id={`${id}-contact`}
            label={t("team.form.contact")}
            description={t("team.form.contactHelp")}
            error={fieldErrorOf(state, fields.contact)}
            required
          >
            <Input name={fields.contact} autoComplete="off" />
          </Field>
          <Field
            id={`${id}-name`}
            label={t("team.form.displayName")}
            error={fieldErrorOf(state, fields.displayName)}
          >
            <Input name={fields.displayName} autoComplete="off" maxLength={200} />
          </Field>
          <CheckboxGroup
            id={`${id}-roles`}
            legend={t("team.form.roles")}
            description={t("team.form.rolesHelp")}
            name={fields.roles}
            options={roles.map((role) => ({
              value: role.value,
              label: role.label,
              description: role.needsMfa ? t("team.form.roleNeedsMfa") : undefined,
            }))}
            error={fieldErrorOf(state, fields.roles)}
            required
          />
          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={pending}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={pending} data-slot="invite-submit">
              {t("team.inviteSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
