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

  const bibliography: string[] = [];
  for (const match of stripLatexComments(referencesBib).matchAll(/^\s*@([a-z]+)\s*\{\s*([^,\s]+)\s*,/gim)) {
    if (!["comment", "preamble", "string"].includes(match[1].toLowerCase())) {
      bibliography.push(match[2].trim());
    }
  }
  const keys = new Set(bibliography);
  const counts = new Map<string, number>();
  for (const key of bibliography) counts.set(key, (counts.get(key) ?? 0) + 1);
  return {
    missingKeys: [...citations].filter((key) => !keys.has(key)).sort(),
    duplicateKeys: [...counts].filter(([, count]) => count > 1).map(([key]) => key).sort(),
  };
}
