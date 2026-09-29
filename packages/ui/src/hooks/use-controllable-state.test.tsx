import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useControllableState } from "./use-controllable-state";

describe("useControllableState", () => {
  it("keeps its own state when uncontrolled and reports changes", () => {
    const onChange = vi.fn();
    const { result } = renderHook(() => useControllableState({ defaultValue: 1, onChange }));
    expect(result.current[0]).toBe(1);
    act(() => result.current[1](2));
    expect(result.current[0]).toBe(2);
    expect(onChange).toHaveBeenCalledWith(2);
  });

  it("follows the controlled value and only reports when controlled", () => {
    const onChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ value }) => useControllableState({ value, defaultValue: 1, onChange }),
      { initialProps: { value: 5 } },
    );
    expect(result.current[0]).toBe(5);
    act(() => result.current[1](6));
    expect(onChange).toHaveBeenCalledWith(6);
    expect(result.current[0]).toBe(5);
    rerender({ value: 6 });
    expect(result.current[0]).toBe(6);
  });
});
