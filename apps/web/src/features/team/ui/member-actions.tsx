"use client";

import { startTransition, useActionState, useId, useRef, useState } from "react";
import {
  Banner,
  Button,
  CheckboxGroup,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  ErrorState,
  Field,
  REASON_MIN_LENGTH,
  Textarea,
  toast,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { fieldErrorOf, idleAction } from "@/shared/lib/action-state";
import type { ActionState } from "@/shared/lib/action-state";
import type { TeamAction, TeamFormFields, TeamRoleOption } from "./invite-dialog";

export interface MemberActionsProps {
  member: { id: string; name: string; roles: readonly string[] };
  screenId: string;
  fields: TeamFormFields;
  roles: readonly TeamRoleOption[];
  changeRoles: TeamAction;
  disable: TeamAction;
  /** The signed-in person: they cannot disable themselves. */
  isSelf: boolean;
  /** The page's hint that this is the only admin; identity's 409 is the authority. */
  lastAdmin: boolean;
}

function Errors({ state, title }: { state: ActionState; title: string }) {
  const problem = state.status === "error" ? state.problem : undefined;
  const formErrors = state.status === "error" ? (state.formErrors ?? []) : [];
  if (problem === undefined && formErrors.length === 0) return null;
  return (
    <div className="flex flex-col gap-3" data-slot="member-errors">
      {problem ? (
        <ErrorState
          title={problem.title}
          detail={problem.detail}
          correlationId={problem.correlationId || undefined}
        />
      ) : null}
      {formErrors.length > 0 ? (
        <Banner tone="danger" title={title}>
          <ul>
            {formErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
    </div>
  );
}

/**
 * One active member's controls: a roles dialog (the roles the kind allows, the current ones
 * ticked) and, for anyone but the signed-in person, a disable dialog that asks for a reason.
 * A refusal keeps the dialog open with identity's words (the last admin, a role the kind
 * lacks); a success closes it and the page shows the change.
 */
export function MemberActions({
  member,
  screenId,
  fields,
  roles,
  changeRoles,
  disable,
  isSelf,
  lastAdmin,
}: MemberActionsProps) {
  const id = useId();
  const [rolesOpen, setRolesOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);
  const [rolesState, rolesAction, rolesPending] = useActionState(
    async (previous: ActionState, formData: FormData): Promise<ActionState> => {
      const state = await changeRoles(previous, formData);
      if (state.status === "ok") {
        setRolesOpen(false);
        if (state.message) toast.success(state.message);
      }
      return state;
    },
    idleAction(),
  );
  const [disableState, disableDispatch, disablePending] = useActionState(
    async (previous: ActionState, formData: FormData): Promise<ActionState> => {
      const state = await disable(previous, formData);
      if (state.status === "ok") {
        setDisableOpen(false);
        if (state.message) toast.success(state.message);
      }
      return state;
    },
    idleAction(),
  );
  const disableForm = useRef<HTMLFormElement>(null);
  const [reason, setReason] = useState("");
  const [reasonTouched, setReasonTouched] = useState(false);
  const reasonTooShort = reason.trim().length < REASON_MIN_LENGTH;
  const reasonError =
    fieldErrorOf(disableState, fields.reason) ??
    (reasonTouched && reasonTooShort
      ? t("team.form.reasonTooShort", { min: REASON_MIN_LENGTH })
      : undefined);

  const submitDisable = () => {
    const form = disableForm.current;
    if (form === null) return;
    const data = new FormData(form);
    data.set(fields.reason, reason.trim());
    startTransition(() => disableDispatch(data));
  };

  return (
    <div className="flex flex-wrap gap-2" data-slot="member-actions">
      <Dialog open={rolesOpen} onOpenChange={setRolesOpen}>
        <DialogTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label={t("team.changeRolesLabel", { name: member.name })}
          >
            {t("team.changeRoles")}
          </Button>
        </DialogTrigger>
        <DialogContent data-slot="roles-dialog">
          <form action={rolesAction} className="flex flex-col gap-5" data-slot="roles-form">
            <DialogHeader>
              <DialogTitle>{t("team.rolesTitle", { name: member.name })}</DialogTitle>
              <DialogDescription>
                {t("team.rolesBody")}
                {lastAdmin ? ` ${t("team.lastAdminHint")}` : ""}
              </DialogDescription>
            </DialogHeader>
            <input type="hidden" name={fields.screen} value={screenId} />
            <input type="hidden" name={fields.userId} value={member.id} />
            <Errors state={rolesState} title={t("team.refused")} />
            <CheckboxGroup
              id={`${id}-roles`}
              legend={t("team.form.roles")}
              name={fields.roles}
              options={roles.map((role) => ({
                value: role.value,
                label: role.label,
                description: role.needsMfa ? t("team.form.roleNeedsMfa") : undefined,
              }))}
              defaultValue={member.roles}
              error={fieldErrorOf(rolesState, fields.roles)}
              required
            />
            <DialogFooter>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setRolesOpen(false)}
                disabled={rolesPending}
              >
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={rolesPending} data-slot="roles-submit">
                {t("team.rolesSubmit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {isSelf ? null : (
        <ConfirmDialog
          open={disableOpen}
          onOpenChange={(open) => {
            setDisableOpen(open);
            if (!open) {
              setReason("");
              setReasonTouched(false);
            }
          }}
          trigger={
            <Button
              variant="secondary"
              size="sm"
              aria-label={t("team.disableLabel", { name: member.name })}
            >
              {t("team.disable")}
            </Button>
          }
          title={t("team.disableTitle", { name: member.name })}
          description={`${t("team.disableBody")}${lastAdmin ? ` ${t("team.lastAdminHint")}` : ""}`}
          confirmLabel={t("team.disableConfirm")}
          cancelLabel={t("common.cancel")}
          destructive
          pending={disablePending}
          confirmDisabled={reasonTooShort}
          onConfirm={submitDisable}
        >
          <form
            ref={disableForm}
            data-slot="disable-form"
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!reasonTooShort) submitDisable();
            }}
          >
            <input type="hidden" name={fields.screen} value={screenId} />
            <input type="hidden" name={fields.userId} value={member.id} />
            <Errors state={disableState} title={t("team.refused")} />
            <Field
              id={`${id}-reason`}
              label={t("team.form.reason")}
              required
              description={`${t("team.form.reasonHelp")} ${t("team.form.reasonTooShort", { min: REASON_MIN_LENGTH })}`}
              error={reasonError}
            >
              <Textarea
                name={fields.reason}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                onBlur={() => setReasonTouched(true)}
                data-slot="disable-reason"
              />
            </Field>
          </form>
        </ConfirmDialog>
      )}
    </div>
  );
}
