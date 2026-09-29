import { CitationCard, JsonView, KeyValue, Stepper, Timeline } from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function ContentSection() {
  return (
    <CatalogueSection id="content" title="Key values, timeline, JSON, stepper and citations">
      <Example label="Key value">
        <KeyValue items={FIXTURES.keyValues} className="w-full max-w-md" />
      </Example>
      <Example label="Timeline">
        <Timeline events={FIXTURES.timeline} className="w-full max-w-md" />
      </Example>
      <Example label="JSON view">
        <JsonView value={FIXTURES.json} label="Example JSON" className="w-full max-w-md" />
      </Example>
      <Example label="Stepper">
        <Stepper steps={FIXTURES.steps} current={1} className="w-full" />
      </Example>
      <Example label="Citation card">
        <CitationCard
          className="w-full max-w-md"
          quote={FIXTURES.quote}
          clauseRef={FIXTURES.clauseRef}
          documentTitle={FIXTURES.documentTitle}
          documentHref={FIXTURES.documentHref}
          verified
          verifiedBy={FIXTURES.reviewer}
        />
        <CitationCard
          className="w-full max-w-md"
          quote={FIXTURES.quote}
          clauseRef={FIXTURES.clauseRef}
          documentTitle={FIXTURES.documentTitle}
          verified={false}
        />
      </Example>
    </CatalogueSection>
  );
}
