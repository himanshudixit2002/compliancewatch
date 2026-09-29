import { cleanup } from "@testing-library/react";
import { afterEach, expect } from "vitest";
import { axeMatchers } from "./axe";

expect.extend(axeMatchers);

// jsdom has no ResizeObserver; a Radix checkbox inside a form measures itself with one.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

afterEach(() => {
  cleanup();
});
