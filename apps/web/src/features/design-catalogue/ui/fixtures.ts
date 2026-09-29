/**
 * Example data for the catalogue. Everything here is obviously synthetic: "Example ..." text,
 * dates in the year 2000, zero identifiers. fixtures.test.ts and catalogue.test.tsx reject the
 * regulatory vocabulary, so no page state can be mistaken for real content.
 */
import type { SelectOption } from "@compliancewatch/ui";

export const EXAMPLE_TEXT = "Example clause text";

export const EXAMPLE_DATE = "2000-01-15";

const OPTIONS: readonly SelectOption[] = [
  { value: "a", label: "Example option A" },
  { value: "b", label: "Example option B" },
  { value: "c", label: "Example option C", disabled: true },
];

export const FIXTURES = {
  text: EXAMPLE_TEXT,
  paragraph:
    "Example clause text that runs long enough to wrap onto a second line, so spacing and line height can be judged.",
  quote: "Example clause text, quoted as stored and never paraphrased.",
  highlight: {
    before: "Example clause text with ",
    mark: "a marked span",
    after: " that a link pointed at.",
  },
  clauseRef: "Example clause 3(1)",
  documentTitle: "Example document title",
  documentHref: "#example-document",
  reviewer: "Example reviewer",
  version: "0.0-example",
  identifier: "00000000-0000-4000-8000-000000000000",
  correlationId: "00000000-0000-4000-8000-00000000abcd",
  awaited: [
    { method: "GET", path: "/v1/example/items", owner: "example owner" },
    { method: "POST", path: "/v1/example/items/{item_id}/decide", owner: "example owner" },
  ],
  rows: [
    {
      id: "row-1",
      name: "Example item one",
      amount: "Rs 1,499.00",
      due: "2000-01-15",
      state: "open",
    },
    {
      id: "row-2",
      name: "Example item two",
      amount: "Rs 250.00",
      due: "2000-02-01",
      state: "done",
    },
    {
      id: "row-3",
      name: "Example item three",
      amount: "Rs 0.00",
      due: "2000-03-31",
      state: "waived",
    },
  ],
  timeline: [
    {
      id: "t1",
      label: "15 Jan 2000",
      dateTime: "2000-01-15",
      title: "Example event recorded",
      tone: "info" as const,
    },
    {
      id: "t2",
      label: "20 Jan 2000",
      dateTime: "2000-01-20",
      title: "Example event approved",
      tone: "success" as const,
    },
    {
      id: "t3",
      label: "31 Jan 2000",
      dateTime: "2000-01-31",
      title: "Example event withdrawn",
      tone: "warning" as const,
    },
  ],
  keyValues: [
    {
      key: "id",
      label: "Identifier",
      value: "00000000-0000-4000-8000-000000000000",
      copy: "00000000-0000-4000-8000-000000000000",
    },
    { key: "owner", label: "Owner", value: "Example owner" },
    { key: "due", label: "Due", value: "15 Jan 2000" },
  ],
  json: {
    example: true,
    count: 3,
    nested: { list: [1, 2, 3], text: EXAMPLE_TEXT, empty: null },
  },
  steps: [
    { id: "one", label: "Example step one", description: "First of three" },
    { id: "two", label: "Example step two" },
    { id: "three", label: "Example step three" },
  ],
  options: OPTIONS,
  calendarMonth: { year: 2000, month: 1 },
  calendarMarks: { "2000-01-10": 1, "2000-01-15": 2, "2000-01-28": 1 } as Readonly<
    Record<string, number>
  >,
} as const;

export type ExampleRow = (typeof FIXTURES.rows)[number];
