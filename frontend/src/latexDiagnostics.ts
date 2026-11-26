export type LatexSourceLocation = {
  filename: "main.tex" | "references.bib";
  line: number;
};

export function findLatexSourceLocation(message: string): LatexSourceLocation | null {
  const match = /(?:^|[^A-Za-z0-9._-])(main\.tex|references\.bib):(\d+)(?::|\b)/i.exec(message);
  if (!match) return null;
  const line = Number(match[2]);
  if (!Number.isSafeInteger(line) || line < 1) return null;
  const filename = match[1].toLowerCase();
  if (filename !== "main.tex" && filename !== "references.bib") return null;
  return {
    filename,
    line,
  };
}

export function sourceOffsetForLine(source: string, line: number): number {
  let offset = 0;
  for (let currentLine = 1; currentLine < line; currentLine += 1) {
    const newline = source.indexOf("\n", offset);
    if (newline < 0) return source.length;
    offset = newline + 1;
  }
  return offset;
}
