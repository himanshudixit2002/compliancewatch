import { ErrorState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export interface SignInUnavailableProps {
  /** The problem's title and detail, which name the variable to set. */
  title: string;
  detail?: string;
}

/** The sign-in page when no provider is configured or the configured one has no form yet. */
export function SignInUnavailable({ title, detail }: SignInUnavailableProps) {
  return (
    <div data-slot="sign-in-unavailable" className="flex max-w-xl flex-col gap-6">
      <PageHeader title={t("signIn.title")} />
      <ErrorState title={title} detail={detail} />
    </div>
  );
}
