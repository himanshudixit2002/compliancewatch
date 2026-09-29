import { cleanup } from "@testing-library/react";
import { afterEach, expect } from "vitest";
import { axeMatchers } from "./axe";

expect.extend(axeMatchers);

afterEach(() => {
  cleanup();
});
