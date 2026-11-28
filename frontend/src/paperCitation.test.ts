import { afterEach, describe, expect, it, vi } from "vitest";
import {
  copyTextToClipboard,
  formatPaperCitation,
  paperDoiForClipboard,
} from "./paperCitation";
import type { Paper } from "./types";

function paper(overrides: Partial<Paper> = {}): Paper {
  return {
    paper_id: "paper-1",
    external_paper_id: "W123",
    api_provider: "openalex",
    title: "Climate adaptation",
    abstract: null,
    publication_year: 2024,
    doi: "https://doi.org/10.1234/Climate.42",
    paper_url: null,
    venue: "Journal of Research",
    citation_count: null,
    authors: [
      { author_id: "author-1", author_name: "Jane Smith" },
      { author_id: "author-2", author_name: "Alex Lee" },
    ],
    saved: false,
    screening_status: "unread",
    screening_note: "",
    screening_exclusion_reason: null,
    screening_decisions: [],
    screening_assignments: [],
    screening_disagreement: false,
    tags: [],
    metadata: {},
    ...overrides,
  };
}

describe("paper citation copying", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("formats available bibliographic details and a canonical DOI URL", () => {
    expect(formatPaperCitation(paper())).toBe(
      "Jane Smith & Alex Lee. (2024). Climate adaptation. Journal of Research. "
      + "https://doi.org/10.1234/Climate.42",
    );
    expect(paperDoiForClipboard(paper())).toBe("10.1234/Climate.42");
  });

  it("handles missing authors, year, venue, and DOI without dangling punctuation", () => {
    const record = paper({
      title: "  Methods review  ",
      authors: [],
      publication_year: null,
      venue: null,
      doi: null,
      paper_url: "https://example.org/methods",
    });

    expect(formatPaperCitation(record)).toBe(
      "Methods review. (n.d.). https://example.org/methods",
    );
    expect(paperDoiForClipboard(record)).toBeNull();
  });

  it("formats multiple authors and cleans DOI prefixes", () => {
    const record = paper({
      authors: [
        { author_id: "1", author_name: "First Author" },
        { author_id: "2", author_name: "Second Author" },
        { author_id: "3", author_name: "Third Author" },
      ],
      doi: "doi: 10.1234/example;",
      paper_url: null,
    });

    expect(formatPaperCitation(record)).toBe(
      "First Author, Second Author, & Third Author. (2024). "
      + "Climate adaptation. Journal of Research. https://doi.org/10.1234/example",
    );
    expect(paperDoiForClipboard(record)).toBe("10.1234/example");
  });

  it("copies a DOI URL when the separate DOI field is missing", () => {
    const record = paper({
      doi: null,
      paper_url: "https://doi.org/10.5678/url-doi",
    });

    expect(paperDoiForClipboard(record)).toBe("10.5678/url-doi");
    expect(formatPaperCitation(record)).toContain("https://doi.org/10.5678/url-doi");
  });

  it("writes the requested value to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await copyTextToClipboard("citation text");

    expect(writeText).toHaveBeenCalledWith("citation text");
  });

  it("reports when clipboard access is unavailable", async () => {
    vi.stubGlobal("navigator", {});

    await expect(copyTextToClipboard("citation text"))
      .rejects.toThrow("Clipboard access is unavailable in this browser.");
  });

  it("propagates clipboard permission failures for the UI to report", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("Permission denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    await expect(copyTextToClipboard("citation text")).rejects.toThrow("Permission denied");
  });
});
