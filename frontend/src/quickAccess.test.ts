import { describe, expect, it } from "vitest";
import {
  mergeQuickAccessSources,
  parseQuickAccessState,
  rememberQuickAccessSource,
  toggleQuickAccessPin,
} from "./quickAccess";
import type { QuickAccessSource, QuickAccessState } from "./types";

function source(
  sourceId: string,
  projectId = "project-1",
  openedAt = "2026-11-26T12:00:00.000Z",
): QuickAccessSource {
  return {
    project_id: projectId,
    project_name: `Project ${projectId}`,
    source_type: "document",
    source_id: sourceId,
    source_title: `Source ${sourceId}`,
    opened_at: openedAt,
  };
}

const empty: QuickAccessState = { recent: [], pinned: [] };

describe("quick access sources", () => {
  it("moves a reopened source to the front and distinguishes projects", () => {
    const next = rememberQuickAccessSource(
      { recent: [source("same"), source("older", "project-2")], pinned: [] },
      source("same", "project-1", "2026-11-26T13:00:00.000Z"),
    );

    expect(next.recent.map((item) => `${item.project_id}:${item.source_id}`)).toEqual([
      "project-1:same",
      "project-2:older",
    ]);
  });

  it("limits recent sources while keeping pins independent", () => {
    const recent = Array.from({ length: 6 }, (_, index) => source(String(index)));
    const pinned = source("important");
    const state = toggleQuickAccessPin({ recent, pinned: [] }, pinned);
    const next = rememberQuickAccessSource(state, source("new"));

    expect(next.recent.map((item) => item.source_id)).toEqual([
      "new", "0", "1", "2", "3", "4",
    ]);
    expect(next.pinned.map((item) => item.source_id)).toEqual(["important"]);
  });

  it("toggles a pin without changing recent history", () => {
    const item = source("important");
    const pinned = toggleQuickAccessPin({ ...empty, recent: [item] }, item);
    const unpinned = toggleQuickAccessPin(pinned, item);

    expect(pinned.pinned).toEqual([item]);
    expect(unpinned.pinned).toEqual([]);
    expect(unpinned.recent).toEqual([item]);
  });

  it("merges legacy project recents by open time without losing pins", () => {
    const pinned = source("saved", "project-1");
    const state = {
      recent: [source("older", "project-1", "2026-11-26T12:00:00.000Z")],
      pinned: [pinned],
    };
    const merged = mergeQuickAccessSources(state, [
      source("newer", "project-2", "2026-11-26T14:00:00.000Z"),
      { ...pinned, project_name: "Renamed project", opened_at: "2026-11-26T13:00:00.000Z" },
    ]);

    expect(merged.recent.map((item) => item.source_id)).toEqual(["newer", "saved", "older"]);
    expect(merged.pinned[0].project_name).toBe("Renamed project");
  });

  it("validates stored quick-access entries", () => {
    expect(() => parseQuickAccessState("{")).toThrow();
    expect(parseQuickAccessState(JSON.stringify({
      recent: [source("valid"), { ...source("bad"), project_id: "" }],
      pinned: [source("pin"), source("pin")],
    }))).toEqual({
      recent: [source("valid")],
      pinned: [source("pin")],
    });
  });
});
