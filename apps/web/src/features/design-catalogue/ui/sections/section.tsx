import type { ReactNode } from "react";

export interface CatalogueSectionProps {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
}

/** One catalogue group: a heading the e2e suite can target and its examples. */
export function CatalogueSection({ id, title, description, children }: CatalogueSectionProps) {
  const headingId = `catalogue-${id}-title`;
  return (
    <section
      id={`catalogue-${id}`}
      aria-labelledby={headingId}
      data-catalogue-section={id}
      className="flex flex-col gap-4 border-t pt-6"
    >
      <div>
        <h2 id={headingId} className="text-xl font-semibold text-fg">
          {title}
        </h2>
        {description ? <p className="text-sm text-fg-muted">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

export interface ExampleProps {
  label: string;
  children: ReactNode;
}

/** A labelled example inside a group. */
export function Example({ label, children }: ExampleProps) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium tracking-wide text-fg-muted uppercase">{label}</p>
      <div className="flex flex-wrap items-start gap-3">{children}</div>
    </div>
  );
}
