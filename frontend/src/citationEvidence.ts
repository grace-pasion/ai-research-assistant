export type CitationRange = { start: number; end: number };

function normalizeWhitespace(text: string): { text: string; offsets: number[] } {
  let normalized = "";
  const offsets: number[] = [];
  const append = (character: string, sourceIndex: number) => {
    normalized += character;
    for (let unit = 0; unit < character.length; unit += 1) {
      offsets.push(sourceIndex);
    }
  };
  let index = 0;
  for (const character of text) {
    if (/\s/u.test(character)) {
      if (normalized && !normalized.endsWith(" ")) {
        append(" ", index);
      }
    } else {
      append(character, index);
    }
    index += 1;
  }
  if (normalized.endsWith(" ")) {
    normalized = normalized.slice(0, -1);
    offsets.pop();
  }
  return { text: normalized, offsets };
}

export function findCitationRange(text: string, excerpt: string | null): CitationRange | null {
  if (!excerpt) return null;
  const normalizedExcerpt = normalizeWhitespace(excerpt).text;
  if (!normalizedExcerpt) return null;
  const stringStart = text.indexOf(excerpt);
  if (stringStart >= 0) {
    const start = Array.from(text.slice(0, stringStart)).length;
    return { start, end: start + Array.from(excerpt).length };
  }

  const normalizedText = normalizeWhitespace(text);
  const normalizedStart = normalizedText.text.indexOf(normalizedExcerpt);
  if (normalizedStart < 0) return null;
  const normalizedEnd = normalizedStart + normalizedExcerpt.length;
  return {
    start: normalizedText.offsets[normalizedStart],
    end: normalizedText.offsets[normalizedEnd - 1] + 1,
  };
}
