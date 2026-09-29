import { useState } from "react";
import { Badge, MonthCalendar } from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function CalendarSection() {
  const [selected, setSelected] = useState<string | null>("2000-01-15");
  return (
    <CatalogueSection
      id="calendar"
      title="Month calendar"
      description="A grid with one focusable cell; arrow keys, Home, End, PageUp and PageDown move it."
    >
      <Example label="January 2000 with example marks">
        <div className="w-full max-w-lg">
          <MonthCalendar
            defaultMonth={FIXTURES.calendarMonth}
            selected={selected}
            onSelect={setSelected}
            renderDay={(day) => {
              const count = FIXTURES.calendarMarks[day.key];
              return count === undefined ? null : (
                <Badge tone="warning" className="mt-1">
                  {count}
                </Badge>
              );
            }}
          />
          <p className="mt-2 text-sm text-fg-muted">Selected: {selected ?? "none"}</p>
        </div>
      </Example>
    </CatalogueSection>
  );
}
