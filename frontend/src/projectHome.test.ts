import { describe, expect, it } from "vitest";
import {
  addRecentProjectSource,
  parseRecentProjectSources,
} from "./projectHome";
import type { RecentProjectSource } from "./types";

function source(
  sourceId: string,
  sourceType: RecentProjectSource["source_type"] = "document",
): RecentProjectSource {
  return {
    source_type: sourceType,
    source_id: sourceId,
    source_title: `${sourceType} ${sourceId}`,
    opened_at: "2026-11-26T12:00:00.000Z",
  };
}

describe("project home recent sources", () => {
  it("moves a reopened source to the front without duplicating it", () => {
    const updated = addRecentProjectSource(
      [source("first"), source("second", "paper")],
      { ...source("first"), opened_at: "2026-11-26T13:00:00.000Z" },
    );

    expect(updated.map((item) => item.source_id)).toEqual(["first", "second"]);
    expect(updated[0].opened_at).toBe("2026-11-26T13:00:00.000Z");
  });

  it("keeps only the six most recently opened distinct sources", () => {
    const recent = Array.from({ length: 7 }, (_, index) => source(String(index)));
    const updated = addRecentProjectSource(recent.slice(0, 6), source("new"));

    expect(updated.map((item) => item.source_id)).toEqual([
      "new", "0", "1", "2", "3", "4",
    ]);
  });

  it("rejects malformed stored JSON and filters invalid entries", () => {
    expect(() => parseRecentProjectSources("{")).toThrow();
    expect(parseRecentProjectSources(JSON.stringify([
      source("valid"),
      { source_type: "document", source_id: "", source_title: "", opened_at: "bad" },
    ])).map((item) => item.source_id)).toEqual(["valid"]);
  });
});
