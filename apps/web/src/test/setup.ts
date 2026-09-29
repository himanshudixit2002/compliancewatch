import { cleanup } from "@testing-library/react";
import { axeMatchers } from "@compliancewatch/ui/test/axe";
import { afterEach, expect, vi } from "vitest";

// The same toHaveNoViolations matcher the ui package uses (written over axe-core).
expect.extend(axeMatchers);

// `import "server-only"` throws outside a React Server Components bundle; unit tests import
// server modules directly, so the marker becomes an empty module here.
vi.mock("server-only", () => ({}));

// Route helpers from next/navigation need a request scope; tests assert on these mocks instead.
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
  notFound: vi.fn(),
  usePathname: vi.fn(() => "/"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  })),
}));

afterEach(() => {
  cleanup();
});
