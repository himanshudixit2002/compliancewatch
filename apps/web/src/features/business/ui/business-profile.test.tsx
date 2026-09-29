import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { businessFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { businessHeader } from "../model/business-pages";
import { REGISTRATION_FIELDS } from "../model/registration-form";
import { BusinessProfile, type RegistrationSection } from "./business-profile";

const BUSINESS = businessHeader(businessFromDto(BUSINESS_DTO));
const PROPS = {
  title: "Profile",
  business: BUSINESS,
  header: { crumbs: [], tabs: [] },
  nodeLinks: {
    [ENTITY_ID]: { attributes: "/a?node=e", snapshot: "/s?node=e" },
    [REGISTRATION_ID]: { attributes: "/a?node=r", snapshot: "/s?node=r" },
  },
  locationFields: {
    businessId: "business_id",
    registrationId: "registration_id",
    label: "label",
    name: "name",
  },
  registration: null,
  addBusinessHref: null,
};

const KEY = "00000000-0000-4000-8000-00000000abcd";

const FORM: RegistrationSection = {
  status: "form",
  action: vi.fn(),
  idempotencyInput: <input type="hidden" name="idempotency_key" value={KEY} />,
  fields: REGISTRATION_FIELDS,
  againHref: "/b/x/profile",
};

describe("BusinessProfile", () => {
  it("shows the entity and each registration with its pages and the location form", async () => {
    const { container } = render(<BusinessProfile {...PROPS} locationAction={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Profile" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 2, name: "Business (PAN)" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 3, name: "29ABCDE1234F1Z5" })).toBeDefined();
    const attributes = screen.getAllByRole("link", { name: "Attributes" });
    expect(attributes.map((link) => link.getAttribute("href"))).toEqual(["/a?node=e", "/a?node=r"]);
    expect(
      screen.getByRole("form", { name: "Add a location under 29ABCDE1234F1Z5" }),
    ).toBeDefined();
    expect(screen.getByText(/Locations are not listed here/)).toBeDefined();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it("offers no form to a reader, and says when there is no registration", () => {
    render(
      <BusinessProfile
        {...PROPS}
        business={{ ...BUSINESS, registrations: [] }}
        nodeLinks={{}}
        locationAction={null}
      />,
    );
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.getByText("No GSTIN registration yet")).toBeDefined();
    expect(screen.queryByRole("link", { name: "Attributes" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Add a GSTIN" })).toBeNull();
  });

  it("offers another GSTIN of the business with the page's key, and the way to another business", async () => {
    render(
      <BusinessProfile
        {...PROPS}
        locationAction={vi.fn()}
        registration={FORM}
        addBusinessHref="/onboarding/business"
      />,
    );
    const section = screen.getByRole("region", { name: "Add a GSTIN" });
    const form = screen.getByRole("form", { name: "Add a GSTIN to Example business" });
    expect(section.contains(form)).toBe(true);
    const hidden = Object.fromEntries(
      [...form.querySelectorAll("input[type='hidden']")].map((input) => [
        input.getAttribute("name"),
        input.getAttribute("value"),
      ]),
    );
    expect(hidden).toEqual({ idempotency_key: KEY, business_id: ENTITY_ID });
    expect(
      screen.getByRole("textbox", { name: /GSTIN/ }).getAttribute("aria-describedby"),
    ).toBeTruthy();
    expect(section.textContent).toContain("then this business's PAN ABCDE1234F");
    expect(section.textContent).toContain("only the demo GSTIN 29ABCDE1234F1Z5");
    expect(screen.getByRole("link", { name: "Add another business" }).getAttribute("href")).toBe(
      "/onboarding/business",
    );
    expect(await runAxe(section)).toHaveNoViolations();
  });

  it("points to the consent step instead of the form while the consents are not on file", () => {
    const { container } = render(
      <BusinessProfile
        {...PROPS}
        locationAction={vi.fn()}
        registration={{ status: "consent-first", consentHref: "/onboarding" }}
        addBusinessHref={null}
        clients
      />,
    );
    expect(screen.queryByRole("form", { name: /Add a GSTIN/ })).toBeNull();
    expect(container.querySelector("[data-slot='registration-consent-first']")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Go to the consent step" }).getAttribute("href")).toBe(
      "/onboarding",
    );
    expect(screen.queryByRole("link", { name: /Add another/ })).toBeNull();
  });
});
