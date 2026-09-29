import {
  Checkbox,
  Field,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  Select,
  Textarea,
} from "@compliancewatch/ui";
import { FIXTURES } from "../fixtures";
import { CatalogueSection, Example } from "./section";

export function FormsSection() {
  return (
    <CatalogueSection
      id="forms"
      title="Form controls"
      description="Field wires the label, description and error to the control."
    >
      <Example label="Text input">
        <Field
          id="example-name"
          label="Example name"
          description="A short description under the control."
          required
        >
          <Input defaultValue="Example value" />
        </Field>
        <Field
          id="example-invalid"
          label="Example with an error"
          error="Example error text explaining what to change."
        >
          <Input defaultValue="wrong" />
        </Field>
        <Field id="example-disabled" label="Disabled">
          <Input disabled defaultValue="Read only" />
        </Field>
      </Example>
      <Example label="Textarea">
        <Field id="example-notes" label="Example notes" description="At least ten characters.">
          <Textarea defaultValue={FIXTURES.paragraph} rows={3} />
        </Field>
      </Example>
      <Example label="Select">
        <Field id="example-select" label="Example choice">
          <Select options={FIXTURES.options} placeholder="Choose one" defaultValue="" />
        </Field>
      </Example>
      <Example label="Checkbox">
        <div className="flex items-center gap-2">
          <Checkbox id="example-check" defaultChecked />
          <Label htmlFor="example-check">Example checked</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="example-uncheck" />
          <Label htmlFor="example-uncheck">Example unchecked</Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="example-check-disabled" disabled />
          <Label htmlFor="example-check-disabled">Disabled</Label>
        </div>
      </Example>
      <Example label="Radio group">
        <RadioGroup defaultValue="a" aria-label="Example choice">
          {FIXTURES.options.map((option) => (
            <div key={option.value} className="flex items-center gap-2">
              <RadioGroupItem
                id={`example-radio-${option.value}`}
                value={option.value}
                disabled={option.disabled}
              />
              <Label htmlFor={`example-radio-${option.value}`}>{option.label}</Label>
            </div>
          ))}
        </RadioGroup>
      </Example>
    </CatalogueSection>
  );
}
