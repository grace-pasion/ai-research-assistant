import { describe, expect, it } from "vitest";
import { getMentionQuery, insertMention } from "./mentions";

describe("annotation mention editing", () => {
  it("finds a username prefix after a word boundary", () => {
    expect(getMentionQuery("Please ask @collab", 18)).toEqual({
      start: 11,
      end: 18,
      query: "collab",
    });
    expect(getMentionQuery("email@collab", 12)).toBeNull();
  });

  it("replaces only the active mention and preserves following text", () => {
    expect(insertMention("Ask @col about this", 8, "colleague")).toEqual({
      value: "Ask @colleague  about this",
      cursor: 15,
    });
  });
});
