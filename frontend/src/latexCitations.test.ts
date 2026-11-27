import { describe, expect, it } from "vitest";
import {
  checkLatexCitationKeys,
  filterCitationPapers,
  findLatexBibliographyStyle,
  hasBibtexCitationKey,
  isValidLatexCitationStyleName,
  updateLatexBibliographyStyle,
} from "./latexCitations";

describe("LaTeX citation-key checks", () => {
  it("finds missing keys across citation variants and optional arguments", () => {
    expect(checkLatexCitationKeys(
      String.raw`\citep[see][p. 10]{smith2024, missing}
\citet{lee2023}
% \cite{commented}
`,
      "@article{smith2024, title={Study}}\n@article{lee2023, title={Review}}",
    )).toEqual({ missingKeys: ["missing"], duplicateKeys: [] });
  });

  it("reports duplicate bibliography keys and ignores nocite-all", () => {
    expect(checkLatexCitationKeys(
      String.raw`\nocite{*}`,
      "@article{same, title={First}}\n@book{same, title={Second}}",
    )).toEqual({ missingKeys: [], duplicateKeys: ["same"] });
  });

  it("does not mistake a commented bibliography style for the active style", () => {
    expect(findLatexBibliographyStyle("% \\bibliographystyle{apalike}\n\\bibliography{references}"))
      .toBeNull();
    expect(findLatexBibliographyStyle("% \\bibliographystyle{apalike}\n\\bibliographystyle{plainnat}"))
      .toBe("plainnat");
  });

  it("distinguishes escaped percent signs from comments after a line break", () => {
    expect(checkLatexCitationKeys(
      String.raw`\% literal \cite{known} \\% \cite{commented}
`,
      "@article{known, title={Study}}",
    )).toEqual({ missingKeys: [], duplicateKeys: [] });
  });

  it("finds citation entries even when their BibTeX key has surrounding whitespace", () => {
    expect(hasBibtexCitationKey("@article{smith2024 , title={Study}}", "smith2024")).toBe(true);
    expect(hasBibtexCitationKey("% @article{smith2024, title={Commented}}\n", "smith2024")).toBe(false);
  });

  it("replaces an active style while preserving commented commands", () => {
    expect(updateLatexBibliographyStyle(
      "% \\bibliographystyle{apalike}\n\\bibliographystyle {plainnat}\n\\bibliography{refs}",
      "custom-style",
    )).toBe("% \\bibliographystyle{apalike}\n\\bibliographystyle{custom-style}\n\\bibliography{refs}");
  });

  it("inserts a style before the bibliography and validates custom style names", () => {
    expect(updateLatexBibliographyStyle(
      "\\begin{document}\nText\n\\bibliography{refs}\n\\end{document}",
      "ieee_like.2",
    )).toContain("\\bibliographystyle{ieee_like.2}\n\n\\bibliography{refs}");
    expect(isValidLatexCitationStyleName("custom-style.2")).toBe(true);
    expect(isValidLatexCitationStyleName("custom}{\\input")).toBe(false);
    expect(() => updateLatexBibliographyStyle("\\begin{document}", "bad}style"))
      .toThrow("Use a style name containing only letters");
  });

  it("filters saved papers case-insensitively across multiple metadata terms", () => {
    const papers = [
      {
        title: "A Study of Research Workflows",
        authors: [{ author_name: "Jane Smith" }],
        publication_year: 2024,
        doi: "10.1234/Research.42",
        venue: "Journal of Methods",
        tags: ["screening"],
        metadata: { stage: "background" },
      },
      {
        title: "A Different Study",
        authors: [{ author_name: "Alex Lee" }],
        publication_year: 2022,
        doi: null,
        venue: "Methods Review",
      },
    ];

    expect(filterCitationPapers(papers, "SMITH 2024")).toEqual([papers[0]]);
    expect(filterCitationPapers(papers, "10.1234/research")).toEqual([papers[0]]);
    expect(filterCitationPapers(papers, "screening background")).toEqual([papers[0]]);
    expect(filterCitationPapers(papers, "no matching paper")).toEqual([]);
    expect(filterCitationPapers(papers, "  ")).toBe(papers);
  });
});
