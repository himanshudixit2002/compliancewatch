"use client";

import { useCallback, useState } from "react";

export interface UseControllableStateOptions<T> {
  /** The controlled value; leave undefined for uncontrolled use. */
  value?: T;
  defaultValue: T;
  onChange?: (value: T) => void;
}

/**
 * State that a parent may control (`value` + `onChange`) or leave to the component
 * (`defaultValue`). The setter always reports through `onChange`.
 */
export function useControllableState<T>({
  value,
  defaultValue,
  onChange,
}: UseControllableStateOptions<T>): [T, (next: T) => void] {
  const [internal, setInternal] = useState<T>(defaultValue);
  const isControlled = value !== undefined;
  const current = isControlled ? value : internal;
  const set = useCallback(
    (next: T) => {
      if (!isControlled) setInternal(next);
      onChange?.(next);
    },
    [isControlled, onChange],
  );
  return [current, set];
}
