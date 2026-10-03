import { describe, expect, it } from "vitest";
import { t } from "@/shared/i18n";
import {
  DATA_REQUEST_KINDS,
  KIND_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
  isOpen,
  newestFirst,
  openRequestOf,
} from "./data-rights";
import type { DataRequest, DataRequestKind, DataRequestStatus } from "./data-rights";

const STATUSES: readonly DataRequestStatus[] = ["received", "in_progress", "completed", "declined"];

function request(
  id: string,
  kind: DataRequestKind,
  status: DataRequestStatus,
  requestedAt = "2026-09-01T05:00:00Z",
): DataRequest {
  return {
    id,
    kind,
    status,
    requestedAt,
    dueBy: "2026-10-01T05:00:00Z",
    closedAt: isOpen({ status }) ? null : "2026-09-15T05:00:00Z",
  };
}

describe("labels and tones", () => {
  it("words every kind and status and gives each status a tone", () => {
    expect(DATA_REQUEST_KINDS.map((kind) => t(KIND_LABEL[kind]))).toEqual([
      "Copy of your data",
      "Deletion of your data",
    ]);
    expect(STATUSES.map((status) => t(STATUS_LABEL[status]))).toEqual([
      "Received",
      "In progress",
      "Completed",
      "Declined",
    ]);
    expect(STATUSES.map((status) => STATUS_TONE[status])).toEqual([
      "info",
      "warning",
      "success",
      "danger",
    ]);
  });
});

describe("isOpen", () => {
  it("is true until a request is completed or declined", () => {
    expect(STATUSES.map((status) => isOpen({ status }))).toEqual([true, true, false, false]);
  });
});

describe("openRequestOf", () => {
  it("finds the open request of a kind and ignores closed ones and other kinds", () => {
    const requests = [
      request("done", "export", "completed"),
      request("erase", "deletion", "received"),
      request("copy", "export", "in_progress"),
    ];
    expect(openRequestOf(requests, "export")?.id).toBe("copy");
    expect(openRequestOf(requests, "deletion")?.id).toBe("erase");
    expect(openRequestOf([request("done", "export", "completed")], "export")).toBeUndefined();
    expect(openRequestOf([], "deletion")).toBeUndefined();
  });
});

describe("newestFirst", () => {
  it("puts the most recent request first without changing the input", () => {
    const input = [
      request("may", "deletion", "declined", "2026-05-04T05:00:00Z"),
      request("oct", "export", "received", "2026-10-01T05:00:00Z"),
      request("aug", "export", "completed", "2026-08-03T05:00:00Z"),
    ];
    expect(newestFirst(input).map((item) => item.id)).toEqual(["oct", "aug", "may"]);
    expect(input[0]?.id).toBe("may");
  });
});
