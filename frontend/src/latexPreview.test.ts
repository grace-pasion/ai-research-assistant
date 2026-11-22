import { describe, expect, it } from "vitest";
import { parseLatexPreview } from "./latexPreview";

describe("LaTeX preview", () => {
  it("extracts the article title, sections, and citation keys for the live preview", () => {
    const preview = parseLatexPreview(String.raw`\title{Evidence & \textit{Methods}}
\author{A. Researcher}
\begin{document}
\maketitle
\section{Findings}
The result is \textbf{promising} \cite{smith2024,lee2023}.
\subsection{Limits}
More work is needed.
\end{document}`);

    expect(preview.title).toBe("Evidence & Methods");
    expect(preview.author).toBe("A. Researcher");
    expect(preview.blocks).toEqual([
      { type: "section", text: "Findings" },
      { type: "paragraph", text: "The result is promising [smith2024; lee2023]." },
      { type: "subsection", text: "Limits" },
      { type: "paragraph", text: "More work is needed." },
    ]);
  });

  it("does not render a preamble or comments as article body text", () => {
    const preview = parseLatexPreview(String.raw`\documentclass{article}
\begin{document}
Visible text. % ignored
\end{document}`);

    expect(preview.blocks).toEqual([{ type: "paragraph", text: "Visible text." }]);
  });
});
