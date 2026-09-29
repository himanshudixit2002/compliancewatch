import type { ComponentType, ReactNode } from "react";

/**
 * Components a registry entry may name in `preview` to render repository data under the
 * not-available notice (the ontology table, the local flag table, the rights section of the
 * privacy notice). None exists yet; each arrives with the package that owns its data, and an
 * unknown name renders nothing rather than a placeholder.
 */
export const PREVIEWS: Readonly<Record<string, ComponentType>> = {};

/** The preview element for a registry name, or null when there is none to render. */
export function renderPreview(name: string | undefined): ReactNode {
  if (name === undefined) return null;
  const Preview = PREVIEWS[name];
  return Preview === undefined ? null : <Preview />;
}
