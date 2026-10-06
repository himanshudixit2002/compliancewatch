import { Banner } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { EditNote as EditNoteView } from "../model/registry";

export interface EditNoteProps {
  note: EditNoteView;
}

/**
 * Why the page offers no edit: the registry entry that plans prompt and model edits, with the
 * routes it waits for and who delivers them, so the page says it in the registry's words.
 */
export function EditNote({ note }: EditNoteProps) {
  return (
    <Banner tone="info" title={t("llm.editTitle", { title: note.title })} data-slot="edit-note">
      <p>{t("llm.editBody")}</p>
      <ul data-slot="edit-awaits" className="mt-1 flex flex-col gap-0.5">
        {note.waitingFor.map((item) => (
          <li key={`${item.method} ${item.path}`}>
            <code className="font-mono text-xs">{`${item.method} ${item.path}`}</code> ({item.owner}
            )
          </li>
        ))}
      </ul>
    </Banner>
  );
}
