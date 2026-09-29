import { cleanup, configure } from "@testing-library/react";
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

// findBy* and waitFor give up after 1 s by default; a form action and its re-render can take
// longer than that on a hosted CI runner, so they wait up to 5 s (a real miss still fails).
configure({ asyncUtilTimeout: 5_000 });

afterEach(() => {
  cleanup();
});
