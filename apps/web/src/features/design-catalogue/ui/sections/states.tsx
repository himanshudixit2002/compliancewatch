import { Button, DraftBanner, EmptyState, ErrorState, NotAvailableYet } from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function StatesSection() {
  return (
    <CatalogueSection
      id="states"
      title="Empty, error, draft and not-available states"
      description="Each state says why, and the error state carries the id to quote to support."
    >
      <Example label="Empty state">
        <EmptyState
          className="w-full max-w-md"
          heading="h3"
          title="No example items yet"
          body="Nothing has been recorded for this example, so there is nothing to list."
          action={
            <Button size="sm" variant="secondary">
              Add an example
            </Button>
          }
        />
      </Example>
      <Example label="Error state">
        <ErrorState
          className="w-full max-w-md"
          title="The example could not be loaded"
          detail={FIXTURES.text}
          status={503}
          correlationId={FIXTURES.correlationId}
          retryHref="#catalogue-states"
        />
      </Example>
      <Example label="Draft banner">
        <div className="w-full max-w-md">
          <DraftBanner version={FIXTURES.version} />
        </div>
      </Example>
      <Example label="Not available yet">
        <NotAvailableYet
          title="Example tool"
          guideRef="12"
          roles={["Example role"]}
          waitingFor={FIXTURES.awaited}
          backHref="#catalogue-states"
        />
        <NotAvailableYet
          title="Example tool whose backend is ready"
          guideRef="12"
          roles={["Example role"]}
          waitingFor={FIXTURES.awaited}
          backendReady
          backHref="#catalogue-states"
        />
        <NotAvailableYet
          title="Example tool without a backend"
          guideRef="12"
          roles={["Example role"]}
          waitingFor={null}
          backHref="#catalogue-states"
        />
      </Example>
    </CatalogueSection>
  );
}
