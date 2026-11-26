import { describe, expect, it } from "vitest";
import { findLatexSourceLocation, sourceOffsetForLine } from "./latexDiagnostics";

describe("LaTeX compiler diagnostics", () => {
  it("finds editor locations in compiler output and citation checks", () => {
    expect(findLatexSourceLocation(
      "PDF compilation failed:\n/tmp/build/source/main.tex:12: Undefined control sequence.",
    )).toEqual({ filename: "main.tex", line: 12 });
    expect(findLatexSourceLocation("Duplicate key (references.bib:7)")).toEqual({
      filename: "references.bib",
      line: 7,
    });
    expect(findLatexSourceLocation("PDF compilation failed without a source line.")).toBeNull();
  });

  it("maps a 1-based source line to its beginning", () => {
    expect(sourceOffsetForLine("one\ntwo\nthree", 2)).toBe(4);
    expect(sourceOffsetForLine("one\ntwo", 5)).toBe(7);
  });
});
