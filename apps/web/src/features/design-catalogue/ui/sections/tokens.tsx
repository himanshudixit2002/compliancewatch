import { COLOR_TOKENS, RADII, TYPE_SCALE } from "@compliancewatch/ui";
import type { ColorToken } from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

/* Tailwind only sees literal class names, so every role is listed here rather than built. */
const SWATCH: Readonly<Record<ColorToken, string>> = {
  bg: "bg-bg",
  surface: "bg-surface",
  "surface-raised": "bg-surface-raised",
  fg: "bg-fg",
  "fg-muted": "bg-fg-muted",
  line: "bg-line",
  "line-strong": "bg-line-strong",
  primary: "bg-primary",
  "primary-fg": "bg-primary-fg",
  accent: "bg-accent",
  "accent-fg": "bg-accent-fg",
  success: "bg-success",
  "success-fg": "bg-success-fg",
  warning: "bg-warning",
  "warning-fg": "bg-warning-fg",
  danger: "bg-danger",
  "danger-fg": "bg-danger-fg",
  info: "bg-info",
  "info-fg": "bg-info-fg",
  focus: "bg-focus",
  overlay: "bg-overlay",
};

const TEXT: Readonly<Record<(typeof TYPE_SCALE)[number], string>> = {
  xs: "text-xs",
  sm: "text-sm",
  base: "text-base",
  lg: "text-lg",
  xl: "text-xl",
  "2xl": "text-2xl",
  "3xl": "text-3xl",
};

const ROUNDED: Readonly<Record<(typeof RADII)[number], string>> = {
  sm: "rounded-sm",
  md: "rounded-md",
  lg: "rounded-lg",
};

export function TokensSection() {
  return (
    <CatalogueSection
      id="tokens"
      title="Colour roles, type scale and radii"
      description="Every colour is a role from tokens.css; the theme control above switches the scheme."
    >
      <Example label="Colour roles">
        <ul className="grid w-full grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {COLOR_TOKENS.map((token) => (
            <li key={token} className="flex flex-col gap-1">
              <span
                aria-hidden="true"
                className={`h-10 w-full rounded-md border ${SWATCH[token]}`}
              />
              <code className="font-mono text-xs text-fg">{token}</code>
            </li>
          ))}
        </ul>
      </Example>
      <Example label="Type scale">
        <ul className="flex w-full flex-col gap-1">
          {TYPE_SCALE.map((size) => (
            <li key={size} className={`${TEXT[size]} text-fg`}>
              <code className="mr-3 font-mono text-xs text-fg-muted">{size}</code>
              {FIXTURES.text}
            </li>
          ))}
        </ul>
      </Example>
      <Example label="Radii">
        {RADII.map((radius) => (
          <span
            key={radius}
            className={`flex size-16 items-center justify-center border bg-surface font-mono text-xs text-fg ${ROUNDED[radius]}`}
          >
            {radius}
          </span>
        ))}
      </Example>
    </CatalogueSection>
  );
}
