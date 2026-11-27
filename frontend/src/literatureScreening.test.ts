import { describe, expect, it } from "vitest";
import {
  exclusionReasonLabel,
  filterAndSortScreeningPapers,
  hasScreeningDisagreement,
} from "./literatureScreening";
import type { Paper, PaperScreeningDecision } from "./types";

function paper(
  title: string,
  status: Paper["screening_status"],
  year: number | null,
  abstract = "",
): Paper {
  return {
    paper_id: title,
    external_paper_id: title,
    api_provider: "openalex",
    title,
    abstract,
    publication_year: year,
    doi: null,
    paper_url: null,
    venue: null,
    citation_count: null,
    authors: [],
    saved: true,
    screening_status: status,
    screening_note: "",
    screening_exclusion_reason: null,
    screening_decisions: [],
    screening_assignments: [],
    screening_disagreement: false,
    tags: [],
    metadata: {},
  };
}

describe("literature screening filters and sorting", () => {
  const papers = [
    paper("Zebra study", "unread", 2021),
    paper("Alpha study", "include", 2024, "A queryable abstract"),
    paper("No date", "exclude", null),
  ];

  it("filters by decision and searches paper metadata", () => {
    expect(filterAndSortScreeningPapers(papers, "include", "queryable", "saved").map((item) => item.title))
      .toEqual(["Alpha study"]);
    expect(filterAndSortScreeningPapers(papers, "all", "zebra", "saved").map((item) => item.title))
      .toEqual(["Zebra study"]);
  });

  it("sorts by title and publication year while keeping missing years last", () => {
    expect(filterAndSortScreeningPapers(papers, "all", "", "title").map((item) => item.title))
      .toEqual(["Alpha study", "No date", "Zebra study"]);
    expect(filterAndSortScreeningPapers(papers, "all", "", "year_desc").map((item) => item.title))
      .toEqual(["Alpha study", "Zebra study", "No date"]);
    expect(filterAndSortScreeningPapers(papers, "all", "", "year_asc").map((item) => item.title))
      .toEqual(["Zebra study", "Alpha study", "No date"]);
  });

  it("flags differing reviewer outcomes or exclusion reasons, but not matching reviews", () => {
    const decision = (
      user_id: string,
      screening_status: PaperScreeningDecision["screening_status"],
      exclusion_reason: PaperScreeningDecision["exclusion_reason"] = null,
    ): PaperScreeningDecision => ({
      user_id,
      user_name: user_id,
      screening_status,
      exclusion_reason,
      screening_note: "",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    expect(hasScreeningDisagreement([
      decision("one", "include"),
      decision("two", "include"),
    ])).toBe(false);
    expect(hasScreeningDisagreement([
      decision("one", "include"),
      decision("two", "exclude", "wrong_outcome"),
    ])).toBe(true);
    expect(hasScreeningDisagreement([
      decision("one", "exclude", "wrong_population"),
      decision("two", "exclude", "wrong_outcome"),
    ])).toBe(true);
    expect(exclusionReasonLabel("wrong_population")).toBe("Wrong population");
  });
});
