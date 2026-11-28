import { describe, expect, it } from "vitest";
import { findAnnotationRange, findCitationRange } from "./citationEvidence";

describe("citation passage location", () => {
  it("finds the exact cited passage in the extracted source text", () => {
    expect(findCitationRange(
      "Introduction. The trial enrolled 120 participants. Results follow.",
      "The trial enrolled 120 participants.",
    )).toEqual({ start: 14, end: 50 });
  });

  it("uses code-point offsets when text before the passage contains non-BMP characters", () => {
    expect(findCitationRange(
      "🧪 Introduction. The trial enrolled 120 participants.",
      "The trial enrolled 120 participants.",
    )).toEqual({ start: 16, end: 52 });
  });

  it("finds chunk excerpts when source extraction has different whitespace", () => {
    expect(findCitationRange(
      "🧪 Intro.\n\nThe  trial enrolled\t120 participants.\nResults follow.",
      "The trial enrolled 120 participants.",
    )).toEqual({ start: 10, end: 47 });
  });

  it("returns no range for missing or empty evidence", () => {
    expect(findCitationRange("Source text.", "Unavailable excerpt")).toBeNull();
    expect(findCitationRange("Source text.", null)).toBeNull();
    expect(findCitationRange("Source text.", "")).toBeNull();
    expect(findCitationRange("Source text.", " \n\t ")).toBeNull();
    expect(findCitationRange("Source \n\t text.", " \n\t ")).toBeNull();
  });

  it("uses saved annotation offsets to select the exact repeated passage", () => {
    expect(findAnnotationRange("Passage one. Passage two.", "Passage", 13, 20))
      .toEqual({ start: 13, end: 20 });
  });

  it("falls back to matching the quote when saved offsets no longer match", () => {
    expect(findAnnotationRange("First passage. Second passage.", "passage", 0, 7))
      .toEqual({ start: 6, end: 13 });
    expect(findAnnotationRange("Source text.", null, null, null)).toBeNull();
  });
});
