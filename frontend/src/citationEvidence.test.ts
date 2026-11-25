import { describe, expect, it } from "vitest";
import { findCitationRange } from "./citationEvidence";

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

  it("returns no range for missing or empty evidence", () => {
    expect(findCitationRange("Source text.", "Unavailable excerpt")).toBeNull();
    expect(findCitationRange("Source text.", null)).toBeNull();
    expect(findCitationRange("Source text.", "")).toBeNull();
  });
});
