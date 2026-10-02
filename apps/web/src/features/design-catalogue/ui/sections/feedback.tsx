import {
  Badge,
  Banner,
  Button,
  ProgressBar,
  Skeleton,
  SkeletonGroup,
  StatusChip,
  TONES,
  toast,
} from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function FeedbackSection() {
  return (
    <CatalogueSection
      id="feedback"
      title="Badges, chips, banners, progress, toasts and skeletons"
      description="Tone colours reinforce the text; the text alone carries the meaning."
    >
      <Example label="Badge">
        {TONES.map((tone) => (
          <Badge key={tone} tone={tone}>
            {tone}
          </Badge>
        ))}
      </Example>
      <Example label="Status chip">
        {TONES.map((tone) => (
          <StatusChip key={tone} status={`example_${tone}`} tone={tone} />
        ))}
      </Example>
      <Example label="Banner">
        <div className="flex w-full flex-col gap-2">
          {TONES.map((tone) => (
            <Banner
              key={tone}
              tone={tone}
              title={`Example ${tone} banner`}
              action={
                <Button size="sm" variant="secondary">
                  Example
                </Button>
              }
            >
              {FIXTURES.text}
            </Banner>
          ))}
        </div>
      </Example>
      <Example label="Progress bar">
        <ProgressBar
          className="w-full max-w-md"
          label="Example progress"
          value={4}
          max={17}
          valueText="4 of 17 done"
        />
      </Example>
      <Example label="Toast">
        <Button variant="secondary" onClick={() => toast(FIXTURES.text)}>
          Plain toast
        </Button>
        <Button variant="secondary" onClick={() => toast.success("Example saved")}>
          Success toast
        </Button>
        <Button variant="secondary" onClick={() => toast.error("Example failed")}>
          Error toast
        </Button>
        <Button variant="secondary" onClick={() => toast.info("Example note")}>
          Info toast
        </Button>
      </Example>
      <Example label="Skeleton">
        <SkeletonGroup className="w-full max-w-md" label="Loading example">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </SkeletonGroup>
      </Example>
    </CatalogueSection>
  );
}
