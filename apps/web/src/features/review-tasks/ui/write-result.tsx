import type { Route } from "next";
import Link from "next/link";
import { t } from "@/shared/i18n";
import type { WriteResult } from "./form-shared";

/** Someone the rulebook names by user id: "you" for the signed-in analyst, else the id. */
export function PersonName({ person }: { person: { userId: string; you: boolean } }) {
  return person.you ? (
    <span data-person="you">{t("workbench.you")}</span>
  ) : (
    <code className="font-mono text-xs break-all" data-person={person.userId}>
      {person.userId}
    </code>
  );
}

/** What a review step answered: the sentence, its details and where to go next. */
export function WriteResultView({ result }: { result: WriteResult }) {
  return (
    <div
      className="flex flex-col gap-1"
      data-slot={result.kind === "already" ? "write-already" : "write-result"}
    >
      <p className="text-sm font-medium text-fg">{result.message}</p>
      {result.details.length === 0 ? null : (
        <ul className="ml-5 list-disc text-sm text-fg" data-slot="write-details">
          {result.details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      )}
      {result.links.map((link) => (
        <Link
          key={link.href}
          href={link.href as Route}
          className="text-sm text-primary underline-offset-2 hover:underline"
        >
          {link.label}
        </Link>
      ))}
    </div>
  );
}
