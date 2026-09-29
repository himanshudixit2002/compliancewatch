import {
  Checkbox,
  CheckboxGroup,
  DateField,
  Field,
  Input,
  Label,
  NumberField,
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
      <Example label="Checkbox group">
        <CheckboxGroup
          id="example-group"
          legend="Example choices"
          description="Tick every one that applies."
          name="example-group"
          options={FIXTURES.options}
          defaultValue={["a"]}
        />
        <CheckboxGroup
          id="example-group-invalid"
          legend="Example with an error"
          name="example-group-invalid"
          options={FIXTURES.options.slice(0, 2)}
          error="Example error text explaining what to change."
          columns={2}
        />
      </Example>
      <Example label="Number field">
        <NumberField id="example-count" label="Example count" min={0} max={100000} />
        <NumberField
          id="example-ratio"
          label="Example ratio"
          integer={false}
          defaultValue="1.5"
          description="A number with a decimal point."
        />
      </Example>
      <Example label="Date field">
        <DateField
          id="example-date"
          label="Example date"
          description="Any day in the year 2000."
          min="2000-01-01"
          max="2000-12-31"
          defaultValue="2000-04-01"
        />
      </Example>
    </CatalogueSection>
  );
}
