import { describe, expect, it } from "vitest";
import {
  hasStudyExtractionChanges,
  studyExtractionValues,
} from "./studyExtraction";
import type { PaperStudyExtraction } from "./types";

const saved: PaperStudyExtraction = {
  population: "Adults",
  methods: "Randomized trial",
  sample_size: "N=100",
  outcomes: "Recovery",
  limitations: "Single site",
  updated_by: "user-1",
  updated_by_name: "Reviewer",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("study extraction drafts", () => {
  it("initializes an empty row without marking it as changed", () => {
    const draft = studyExtractionValues(null);

    expect(draft).toEqual({
      population: "",
      methods: "",
      sample_size: "",
      outcomes: "",
      limitations: "",
    });
    expect(hasStudyExtractionChanges(draft, null)).toBe(false);
  });

  it("detects edits and clears against the saved row", () => {
    const draft = studyExtractionValues(saved);

    expect(hasStudyExtractionChanges(draft, saved)).toBe(false);
    expect(hasStudyExtractionChanges({ ...draft, outcomes: "" }, saved)).toBe(true);
    expect(hasStudyExtractionChanges({ ...draft, limitations: "Expanded limits" }, saved)).toBe(true);
  });
});
