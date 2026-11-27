import { describe, expect, it } from "vitest";
import { findPaperSimilarityMatches } from "./paperSimilarity";
import type { Paper } from "./types";

function paper(
  paperId: string,
  title: string,
  overrides: Partial<Paper> = {},
): Paper {
  return {
    paper_id: paperId,
    external_paper_id: paperId,
    api_provider: "openalex",
    title,
    abstract: null,
    publication_year: null,
    doi: null,
    paper_url: null,
    venue: null,
    citation_count: null,
    authors: [],
    saved: true,
    screening_status: "unread",
    screening_note: "",
    screening_exclusion_reason: null,
    screening_decisions: [],
    screening_disagreement: false,
    tags: [],
    metadata: {},
    ...overrides,
  };
}

describe("paper similarity matches", () => {
  it("finds the same DOI across provider URLs and differing titles", () => {
    const candidate = paper("new", "A different provider title", {
      doi: "10.1234/Example",
    });
    const saved = paper("saved", "Imported title", {
      paper_url: "https://doi.org/10.1234/example.",
    });

    expect(findPaperSimilarityMatches(candidate, [saved])).toMatchObject([
      { paper: saved, kind: "possible_duplicate", reason: "Same DOI" },
    ]);
  });

  it("finds title duplicates without DOI despite different metadata", () => {
    const candidate = paper("new", "A Systematic Review of Climate-Change Adaptation", {
      publication_year: 2025,
      authors: [{ author_id: "a", author_name: "New Author" }],
    });
    const saved = paper("saved", "systématic review: climate change adaptation", {
      doi: "10.1111/unrelated-metadata",
      publication_year: 2011,
      authors: [{ author_id: "b", author_name: "Different Author" }],
    });

    expect(findPaperSimilarityMatches(candidate, [saved])).toMatchObject([
      { paper: saved, kind: "possible_duplicate" },
    ]);
  });

  it("shows related titles without requiring matching DOI, author, or year", () => {
    const candidate = paper("new", "Climate adaptation planning for coastal towns");
    const saved = paper("saved", "Climate adaptation in coastal communities");

    expect(findPaperSimilarityMatches(candidate, [saved])).toMatchObject([
      { paper: saved, kind: "related", reason: "Titles share key terms" },
    ]);
  });

  it("does not suggest unrelated papers or the same saved paper ID", () => {
    const candidate = paper("same", "Climate adaptation for coastal communities");
    const saved = paper("same", "Climate adaptation for coastal communities");
    const unrelated = paper("unrelated", "Protein folding in deep learning");

    expect(findPaperSimilarityMatches(candidate, [saved, unrelated])).toEqual([]);
  });

  it("orders possible duplicates before related papers", () => {
    const candidate = paper("new", "Climate adaptation planning for coastal towns");
    const related = paper("related", "Climate adaptation in coastal communities");
    const duplicate = paper("duplicate", "Climate adaptation planning for coastal towns");

    expect(findPaperSimilarityMatches(candidate, [related, duplicate]).map((match) => match.paper.paper_id))
      .toEqual(["duplicate", "related"]);
  });
});
