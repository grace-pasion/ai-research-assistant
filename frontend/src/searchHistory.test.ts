import { describe, expect, it } from "vitest";
import {
  crossProjectSearchActiveFilterLabels,
  crossProjectSearchParams,
  literatureSearchRequest,
} from "./searchHistory";
import type { CrossProjectSearchRecord, SearchQueryHistoryRecord } from "./types";

describe("reproducible search parameters", () => {
  it("shows the submitted cross-project filters without exposing paging limits", () => {
    expect(crossProjectSearchActiveFilterLabels(
      "q=methods+study&limit=50&project_id=project-1&source_type=paper&author=Jane+Doe&year=2024&tag=cohort",
      [{ project_id: "project-1", project_name: "Clinical studies" }],
    )).toEqual([
      "Search: methods study",
      "Project: Clinical studies",
      "Source type: Papers",
      "Author: Jane Doe",
      "Year: 2024",
      "Tag: cohort",
    ]);
  });

  it("rebuilds the cross-project query and every recorded filter", () => {
    const record: CrossProjectSearchRecord = {
      record_id: "record-1",
      query_text: "neural systems",
      provider: "project_library",
      searched_at: "2026-01-10T12:00:00Z",
      filters: {
        author: "Alice Smith",
        limit: 25,
        project_id: "project-1",
        source_type: "paper",
        tag: "methods",
        year: 2021,
      },
      result_count: 3,
    };

    expect(crossProjectSearchParams(record).toString()).toBe(
      "q=neural+systems&author=Alice+Smith&limit=25&project_id=project-1&source_type=paper&tag=methods&year=2021",
    );
  });

  it("reruns a literature record with its exact query, provider, and limit", () => {
    const record: SearchQueryHistoryRecord = {
      query_id: "query-1",
      query_text: "climate models",
      api_provider: "crossref",
      searched_at: "2026-01-10T12:00:00Z",
      search_filters: { limit: 7 },
      result_count: 4,
    };

    expect(literatureSearchRequest(record)).toEqual({
      query: "climate models",
      provider: "crossref",
      limit: 7,
    });
  });
});
