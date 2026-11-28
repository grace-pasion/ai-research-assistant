import { describe, expect, it } from "vitest";
import { acceptLatexFormattingSuggestion } from "./latexFormatting";

describe("LaTeX formatting suggestions", () => {
  it("accepts the exact formatter output while the source is unchanged", () => {
    expect(acceptLatexFormattingSuggestion(
      "\\begin{document}\ntext\n\\end{document}\n",
      {
        sourceSnapshot: "\\begin{document}\ntext\n\\end{document}\n",
        formattedSource: "\\begin{document}\n  text\n\\end{document}\n",
        diff: "-text\n+  text\n",
      },
    )).toBe("\\begin{document}\n  text\n\\end{document}\n");
  });

  it("refuses to accept a suggestion after the document has changed", () => {
    expect(acceptLatexFormattingSuggestion(
      "\\begin{document}\nnew text\n\\end{document}\n",
      {
        sourceSnapshot: "\\begin{document}\nold text\n\\end{document}\n",
        formattedSource: "\\begin{document}\n  old text\n\\end{document}\n",
        diff: "-old text\n+  old text\n",
      },
    )).toBeNull();
  });
});
