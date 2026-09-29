import { Button } from "@compliancewatch/ui";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";

export interface SignOutButtonProps {
  variant?: "secondary" | "ghost";
  size?: "sm" | "md";
}

/**
 * A plain form that POSTs to the sign-out handler: it works without JavaScript, the handler
 * clears the cookie, and the browser follows the redirect to the sign-in page.
 */
export function SignOutButton({ variant = "secondary", size = "sm" }: SignOutButtonProps) {
  return (
    <form method="post" action={hrefFor(screenById("system.sign-out"))} data-slot="sign-out">
      <Button type="submit" variant={variant} size={size}>
        {t("common.signOut")}
      </Button>
    </form>
  );
}
