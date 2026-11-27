import { insertAtCursor } from "./latexEditor";

const citationCommands = [
  "citeauthor",
  "citeyearpar",
  "citealp",
  "citealt",
  "citeyear",
  "citet",
  "citep",
  "nocite",
  "cite",
];

export type LatexCitationIssues = {
  missingKeys: string[];
  duplicateKeys: string[];
};

type CitationSearchPaper = {
  title: string;
  authors: { author_name: string }[];
  publication_year: number | null;
  doi: string | null;
  venue: string | null;
  tags?: string[];
  metadata?: Record<string, string>;
};

export function stripLatexComments(source: string): string {
  return source.split(/(\r?\n)/).map((part, partIndex) => {
    if (partIndex % 2 === 1) return part;
    let backslashes = 0;
    for (let index = 0; index < part.length; index += 1) {
      if (part[index] === "%" && backslashes % 2 === 0) {
        return part.slice(0, index) + " ".repeat(part.length - index);
      }
      backslashes = part[index] === "\\" ? backslashes + 1 : 0;
    }
    return part;
  }).join("");
}

export function findLatexBibliographyStyle(source: string): string | null {
  return stripLatexComments(source).match(/\\bibliographystyle\s*\{([^}]+)\}/)?.[1].trim() ?? null;
}

export function isValidLatexCitationStyleName(style: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(style);
}

export function updateLatexBibliographyStyle(source: string, style: string): string {
  if (!isValidLatexCitationStyleName(style)) {
    throw new Error("Use a style name containing only letters, numbers, periods, underscores, and hyphens.");
  }

  const command = `\\bibliographystyle{${style}}`;
  const activeSource = stripLatexComments(source);
  const activeStyle = activeSource.match(/\\bibliographystyle\s*\{[^}]*\}/);
  if (activeStyle?.index !== undefined) {
    return source.slice(0, activeStyle.index)
      + command
      + source.slice(activeStyle.index + activeStyle[0].length);
  }

  const bibliographyAt = activeSource.lastIndexOf("\\bibliography");
  const documentEndAt = activeSource.lastIndexOf("\\end{document}");
  const insertionAt = bibliographyAt >= 0
    ? bibliographyAt
    : documentEndAt >= 0 ? documentEndAt : source.length;
  return insertAtCursor(source, command, insertionAt).source;
}

export function filterCitationPapers<T extends CitationSearchPaper>(papers: T[], query: string): T[] {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  if (!terms.length) return papers;

  return papers.filter((paper) => {
    const searchableText = [
      paper.title,
      ...paper.authors.map((author) => author.author_name),
      paper.publication_year,
      paper.doi,
      paper.venue,
      ...(paper.tags ?? []),
      ...Object.entries(paper.metadata ?? {}).flat(),
    ].join(" ").toLowerCase();
    return terms.every((term) => searchableText.includes(term));
  });
}

function extractBibtexKeys(referencesBib: string): string[] {
  const keys: string[] = [];
  for (const match of stripLatexComments(referencesBib).matchAll(/^\s*@([a-z]+)\s*\{\s*([^,\s]+)\s*,/gim)) {
    if (!["comment", "preamble", "string"].includes(match[1].toLowerCase())) {
      keys.push(match[2].trim());
    }
  }
  return keys;
}

export function hasBibtexCitationKey(referencesBib: string, key: string): boolean {
  return extractBibtexKeys(referencesBib).includes(key);
}

export function checkLatexCitationKeys(mainTex: string, referencesBib: string): LatexCitationIssues {
  const commandPattern = new RegExp(
    `\\\\(?:${citationCommands.join("|")})\\*?(?:\\s*\\[[^\\]]*\\]){0,2}\\s*\\{([^{}]*)\\}`,
    "g",
  );
  const citations = new Set<string>();
  for (const match of stripLatexComments(mainTex).matchAll(commandPattern)) {
    for (const key of match[1].split(",").map((item) => item.trim())) {
      if (key && key !== "*") citations.add(key);
    }
  }

  const bibliography = extractBibtexKeys(referencesBib);
  const keys = new Set(bibliography);
  const counts = new Map<string, number>();
  for (const key of bibliography) counts.set(key, (counts.get(key) ?? 0) + 1);
  return {
    missingKeys: [...citations].filter((key) => !keys.has(key)).sort(),
    duplicateKeys: [...counts].filter(([, count]) => count > 1).map(([key]) => key).sort(),
  };
}
