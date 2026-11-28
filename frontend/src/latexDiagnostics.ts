export type LatexSourceLocation = {
  filename: "main.tex" | "references.bib";
  line: number | null;
};

export function findLatexSourceLocation(message: string): LatexSourceLocation | null {
  const match = /(?:^|[^A-Za-z0-9._-])(main\.tex|references\.bib)(?::(\d+)(?::|\b)|(?=$|[\s),:]))/i.exec(message);
  if (!match) return null;
  const line = match[2] === undefined ? null : Number(match[2]);
  if (line !== null && (!Number.isSafeInteger(line) || line < 1)) return null;
  const filename = match[1].toLowerCase();
  if (filename !== "main.tex" && filename !== "references.bib") return null;
  return {
    filename,
    line,
  };
}

export function sourceLineAt(source: string, line: number): string | null {
  if (!Number.isSafeInteger(line) || line < 1) return null;
  let start = 0;
  for (let currentLine = 1; currentLine < line; currentLine += 1) {
    const newline = source.indexOf("\n", start);
    if (newline < 0) return null;
    start = newline + 1;
  }
  if (start > source.length) return null;
  const newline = source.indexOf("\n", start);
  const end = newline < 0 ? source.length : newline;
  return source.slice(start, end).replace(/\r$/, "");
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
