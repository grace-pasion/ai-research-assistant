import { describe, expect, it } from "vitest";
import { findLatexSourceLocation, sourceLineAt, sourceOffsetForLine } from "./latexDiagnostics";

describe("LaTeX compiler diagnostics", () => {
  it("finds editor locations in compiler output and citation checks", () => {
    expect(findLatexSourceLocation(
      "PDF compilation failed:\n/tmp/build/source/main.tex:12: Undefined control sequence.",
    )).toEqual({ filename: "main.tex", line: 12 });
    expect(findLatexSourceLocation("Duplicate key (references.bib:7)")).toEqual({
      filename: "references.bib",
      line: 7,
    });
    expect(findLatexSourceLocation("BibTeX reported an error in references.bib")).toEqual({
      filename: "references.bib",
      line: null,
    });
    expect(findLatexSourceLocation("main.tex:0: Invalid line")).toBeNull();
    expect(findLatexSourceLocation("main.tex.backup:12: Invalid file")).toBeNull();
    expect(findLatexSourceLocation("PDF compilation failed without a source line.")).toBeNull();
  });

  it("extracts a source line without newline artifacts and rejects missing lines", () => {
    expect(sourceLineAt("one\r\ntwo\r\nthree", 2)).toBe("two");
    expect(sourceLineAt("one\n", 2)).toBe("");
    expect(sourceLineAt("one\ntwo", 4)).toBeNull();
    expect(sourceLineAt("one\ntwo", 0)).toBeNull();
  });

  it("maps a 1-based source line to its beginning", () => {
    expect(sourceOffsetForLine("one\ntwo\nthree", 2)).toBe(4);
    expect(sourceOffsetForLine("one\ntwo", 5)).toBe(7);
  });
});
