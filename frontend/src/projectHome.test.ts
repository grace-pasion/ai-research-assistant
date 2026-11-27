import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProjectHome } from "./ProjectHome.tsx";
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

function renderProjectHome(sourceDataLoaded: boolean, canEditProject = true): string {
  return renderToStaticMarkup(createElement(ProjectHome, {
    projectId: "project",
    documents: [],
    papersCount: 0,
    canEditProject,
    sourceDataLoaded,
    recentSources: [],
    recentSourcesError: "",
    request: async <T,>() => [] as T,
    onOpenSection: () => undefined,
    onUploadDocuments: () => undefined,
    onOpenSource: () => undefined,
  }));
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

describe("project home getting-started guidance", () => {
  it("waits until source data has loaded before showing the empty-project guide", () => {
    expect(renderProjectHome(false)).not.toContain("Build your research workspace");
    expect(renderProjectHome(true)).toContain("Build your research workspace");
  });

  it("offers document upload only to project editors", () => {
    expect(renderProjectHome(true)).toContain("Upload documents");
    expect(renderProjectHome(true, false)).not.toContain("Upload documents");
    expect(renderProjectHome(true, false)).toContain(
      "Ask a project owner or editor to upload documents.",
    );
  });
});
