import { describe, expect, it } from "vitest";
import { documentBodyInsertionPosition, insertAtCursor } from "./latexEditor";

describe("LaTeX editor insertion", () => {
  const source = "\\documentclass{article}\n\\begin{document}\nText\n\\end{document}";

  it("uses the current cursor only inside the document body", () => {
    const bodyPosition = source.indexOf("Text") + 2;
    const endPosition = source.indexOf("\\end{document}");
    expect(documentBodyInsertionPosition(source, bodyPosition)).toBe(bodyPosition);
    expect(documentBodyInsertionPosition(source, null)).toBe(endPosition);
    expect(documentBodyInsertionPosition(source, source.indexOf("\\documentclass") + 5)).toBe(endPosition);
    expect(documentBodyInsertionPosition(source, source.length)).toBe(endPosition);
  });

  it("returns the cursor after the inserted text and spacing", () => {
    const position = source.indexOf("\\end{document}");
    const inserted = insertAtCursor(source, "\\input{python-output/table.tex}", position);
    expect(inserted.source.indexOf("\\input{python-output/table.tex}"))
      .toBeLessThan(inserted.source.indexOf("\\end{document}"));
    expect(inserted.source.slice(inserted.cursorPosition)).toBe("\\end{document}");
  });
});
