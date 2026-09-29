"use client";

import { useState } from "react";
import { Button } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

export type ThemeChoice = "light" | "dark" | "system";

const CHOICES: readonly ThemeChoice[] = ["light", "dark", "system"];

/** The scheme the root element is forced to: .light, .dark, or neither (the OS decides). */
export function readTheme(root: Element): ThemeChoice {
  if (root.classList.contains("dark")) return "dark";
  if (root.classList.contains("light")) return "light";
  return "system";
}

export function applyTheme(root: Element, choice: ThemeChoice): void {
  root.classList.remove("light", "dark");
  if (choice !== "system") root.classList.add(choice);
}

/** Forces light or dark on <html> for the catalogue, or hands the choice back to the OS. */
export function ThemeToggle() {
  // The server never forces a scheme, so the first client render reads the same "system" the
  // server rendered; after a client-side navigation the class set earlier is picked up here.
  const [choice, setChoice] = useState<ThemeChoice>(() =>
    typeof document === "undefined" ? "system" : readTheme(document.documentElement),
  );
  const select = (next: ThemeChoice) => {
    applyTheme(document.documentElement, next);
    setChoice(next);
  };
  return (
    <div role="group" aria-label={t("design.title")} className="flex gap-1">
      {CHOICES.map((option) => (
        <Button
          key={option}
          size="sm"
          variant={option === choice ? "primary" : "secondary"}
          aria-pressed={option === choice}
          onClick={() => select(option)}
          data-theme-choice={option}
        >
          {t(`design.theme.${option}`)}
        </Button>
      ))}
    </div>
  );
}
