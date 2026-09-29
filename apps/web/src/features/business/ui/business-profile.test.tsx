import { render, screen } from "@testing-library/react";
import { runAxe } from "@compliancewatch/ui/test/axe";
import { describe, expect, it, vi } from "vitest";
import { businessFromDto } from "@/entities/business/mappers";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { businessHeader } from "../model/business-pages";
import { BusinessProfile } from "./business-profile";

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
  });
});
