import { Banner, type BannerProps } from "./banner";

export const DRAFT_BANNER_TEXT = "Draft - to be reviewed by a lawyer";

export interface DraftBannerProps extends Omit<BannerProps, "tone" | "title" | "children"> {
  /** The document's Version line, for example "0.1-draft". */
  version: string;
}

/** Sits above every legal document rendered from docs/legal while its version ends in -draft. */
export function DraftBanner({ version, ...props }: DraftBannerProps) {
  return (
    <Banner tone="warning" title={DRAFT_BANNER_TEXT} data-slot="draft-banner" {...props}>
      Version {version}. The wording has not been approved and may change.
    </Banner>
  );
}
