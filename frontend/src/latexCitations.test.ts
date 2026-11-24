import { describe, expect, it } from "vitest";
import { checkLatexCitationKeys, findLatexBibliographyStyle } from "./latexCitations";

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
});
