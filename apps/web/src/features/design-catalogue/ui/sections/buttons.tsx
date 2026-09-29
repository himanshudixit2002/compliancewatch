import { Button } from "@compliancewatch/ui";
import { CatalogueSection, Example } from "./section";

const VARIANTS = ["primary", "secondary", "ghost", "danger", "link"] as const;
const SIZES = ["sm", "md", "lg"] as const;

export function ButtonsSection() {
  return (
    <CatalogueSection id="buttons" title="Buttons">
      <Example label="Variants">
        {VARIANTS.map((variant) => (
          <Button key={variant} variant={variant}>
            {variant}
          </Button>
        ))}
      </Example>
      <Example label="Sizes">
        {SIZES.map((size) => (
          <Button key={size} size={size} variant="secondary">
            size {size}
          </Button>
        ))}
        <Button size="icon" variant="secondary" aria-label="Example icon button">
          <span aria-hidden="true">+</span>
        </Button>
      </Example>
      <Example label="States">
        <Button loading>Saving</Button>
        <Button disabled>Disabled</Button>
        <Button asChild variant="link">
          <a href="#catalogue-buttons">Rendered as a link</a>
        </Button>
      </Example>
    </CatalogueSection>
  );
}
