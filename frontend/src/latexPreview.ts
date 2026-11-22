export type LatexPreviewBlock = {
  type: "section" | "subsection" | "paragraph";
  text: string;
};

export type LatexPreview = {
  title: string;
  author: string;
  blocks: LatexPreviewBlock[];
};

function commandValue(source: string, command: string): string {
  const match = source.match(new RegExp(`\\\\${command}\\s*\\{((?:[^{}]|\\{[^{}]*\\})*)\\}`));
  return match?.[1]?.trim() ?? "";
}

function cleanInlineLatex(source: string): string {
  return source
    .replace(/\\(?:textbf|textit|emph|texttt)\{([^{}]*)\}/g, "$1")
    .replace(/\\(?:citep|citet|cite)\{([^{}]*)\}/g, (_match, keys: string) =>
      `[${keys.split(",").map((key) => key.trim()).join("; ")}]`,
    )
    .replace(/\\url\{([^{}]*)\}/g, "$1")
    .replace(/\\(?:noindent|newline|linebreak)\b/g, "")
    .replace(/\\\\/g, "\n")
    .replace(/\\([#$%&_{}])/g, "$1")
    .replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?/g, "")
    .replace(/[{}]/g, "")
    .trim();
}

export function parseLatexPreview(source: string): LatexPreview {
  const withoutComments = source.replace(/(^|[^\\])%.*$/gm, "$1");
  const title = cleanInlineLatex(commandValue(withoutComments, "title"));
  const author = cleanInlineLatex(commandValue(withoutComments, "author"));
  const documentStart = withoutComments.indexOf("\\begin{document}");
  const documentEnd = withoutComments.indexOf("\\end{document}");
  let body = documentStart >= 0
    ? withoutComments.slice(documentStart + "\\begin{document}".length, documentEnd >= 0 ? documentEnd : undefined)
    : withoutComments;

  body = body
    .replace(/\\(?:maketitle|tableofcontents)\b/g, "")
    .replace(/\\begin\{abstract\}([\s\S]*?)\\end\{abstract\}/g, "$1")
    .replace(/\\bibliographystyle\{[^}]*\}/g, "")
    .replace(/\\bibliography\{[^}]*\}/g, "");

  const blocks: LatexPreviewBlock[] = [];
  const sections = body.split(/(\\(?:section|subsection)\*?\{[^}]*\})/g);
  for (const section of sections) {
    const heading = section.match(/^\\(section|subsection)\*?\{([^}]*)\}$/);
    if (heading) {
      const text = cleanInlineLatex(heading[2]);
      if (text) blocks.push({ type: heading[1] as "section" | "subsection", text });
      continue;
    }
    for (const paragraph of section.split(/\n\s*\n/)) {
      const text = cleanInlineLatex(paragraph);
      if (text) blocks.push({ type: "paragraph", text });
    }
  }
  return { title, author, blocks };
}
