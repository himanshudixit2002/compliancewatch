// @vitest-environment node
import { revalidatePath, updateTag } from "next/cache";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CacheTagError,
  GLOBAL_REVALIDATE_SECONDS,
  MAX_TAG_LENGTH,
  afterMutation,
  cacheTag,
  cachedRead,
  tags,
  uncachedRead,
} from "./cache";

vi.mock("next/cache", () => ({ updateTag: vi.fn(), revalidatePath: vi.fn() }));

afterEach(() => {
  vi.clearAllMocks();
});

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";

describe("cacheTag", () => {
  it("joins the service, the record and the parts with colons", () => {
    expect(cacheTag("identity", "plans")).toBe("identity:plans");
    expect(cacheTag("profile", "node", TENANT, "n1")).toBe(`profile:node:${TENANT}:n1`);
  });

  it("refuses an empty part, a part holding the separator and an over-long tag", () => {
    expect(() => cacheTag("identity", "")).toThrow(CacheTagError);
    expect(() => cacheTag("identity", "a:b")).toThrow(/must not contain/);
    expect(() => cacheTag("rulebook", "document", "x".repeat(MAX_TAG_LENGTH))).toThrow(
      /longer than 256/,
    );
  });
});

describe("tags", () => {
  it("builds the same string for the same record every time", () => {
    expect(tags.identity.plans()).toBe("identity:plans");
    expect(tags.identity.plans()).toBe(tags.identity.plans());
    expect(tags.identity.consents(TENANT, "owner-1")).toBe(`identity:consents:${TENANT}:owner-1`);
    expect(tags.profile.node(TENANT, "node-1")).toBe(`profile:node:${TENANT}:node-1`);
    expect(tags.profile.ontology()).toBe("profile:ontology");
    expect(tags.rulebook.rules()).toBe("rulebook:rules");
    expect(tags.rulebook.document("doc-1")).toBe("rulebook:document:doc-1");
    expect(tags.rulebook.clause("clause-1")).toBe("rulebook:clause:clause-1");
    expect(tags.notification.templates()).toBe("notification:templates");
    expect(tags.llm.prompts()).toBe("llm-gateway:prompts");
    expect(tags.llm.models()).toBe("llm-gateway:models");
  });

  it("keeps every tag within Next's limit", () => {
    const all = [
      tags.identity.plans(),
      tags.identity.consents(TENANT, "x".repeat(60)),
      tags.profile.node(TENANT, TENANT),
      tags.profile.ontology(),
      tags.rulebook.rules(),
      tags.rulebook.document(TENANT),
      tags.rulebook.clause(TENANT),
      tags.notification.templates(),
      tags.llm.prompts(),
      tags.llm.models(),
    ];
    for (const tag of all) expect(tag.length).toBeLessThanOrEqual(MAX_TAG_LENGTH);
    expect(new Set(all).size).toBe(all.length);
  });
});

describe("cachedRead", () => {
  it("asks Next for five minutes under the tags by default", () => {
    expect(cachedRead([tags.identity.plans()])).toEqual({
      next: { revalidate: GLOBAL_REVALIDATE_SECONDS, tags: ["identity:plans"] },
    });
    expect(GLOBAL_REVALIDATE_SECONDS).toBe(300);
  });

  it("takes another positive whole number of seconds and copies the tag list", () => {
    const list = [tags.llm.prompts(), tags.llm.models()];
    const options = cachedRead(list, 60);
    expect(options.next?.revalidate).toBe(60);
    expect(options.next?.tags).toEqual(list);
    expect(options.next?.tags).not.toBe(list);
  });

  it("refuses a read without a tag or with a revalidate that is not a positive integer", () => {
    expect(() => cachedRead([])).toThrow(/at least one tag/);
    expect(() => cachedRead([tags.rulebook.rules()], 0)).toThrow(/positive/);
    expect(() => cachedRead([tags.rulebook.rules()], 1.5)).toThrow(/positive/);
  });
});

describe("uncachedRead", () => {
  it("is no-store and nothing else", () => {
    expect(uncachedRead()).toEqual({ cache: "no-store" });
  });
});

describe("afterMutation", () => {
  it("expires each tag with updateTag and refreshes each path with revalidatePath", () => {
    afterMutation({
      tags: [tags.identity.plans(), tags.rulebook.rules()],
      paths: ["/settings/billing"],
    });
    expect(updateTag).toHaveBeenCalledTimes(2);
    expect(updateTag).toHaveBeenNthCalledWith(1, "identity:plans");
    expect(updateTag).toHaveBeenNthCalledWith(2, "rulebook:rules");
    expect(revalidatePath).toHaveBeenCalledTimes(1);
    expect(revalidatePath).toHaveBeenCalledWith("/settings/billing");
  });

  it("does nothing with an empty invalidation", () => {
    afterMutation({});
    afterMutation({ tags: [], paths: [] });
    expect(updateTag).not.toHaveBeenCalled();
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});
