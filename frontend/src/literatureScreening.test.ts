import { describe, expect, it } from "vitest";
import { filterAndSortScreeningPapers } from "./literatureScreening";
import type { Paper } from "./types";

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
});
