export function insertAtCursor(
  source: string,
  insertion: string,
  position: number,
): { source: string; cursorPosition: number } {
  const at = Math.max(0, Math.min(position, source.length));
  const before = source.slice(0, at);
  const after = source.slice(at);
  const prefix = before && !/\s$/.test(before) ? "\n\n" : "";
  const suffix = after && !/^\s/.test(after) ? "\n\n" : "";
  return {
    source: `${before}${prefix}${insertion}${suffix}${after}`,
    cursorPosition: at + prefix.length + insertion.length + suffix.length,
  };
}

export function documentBodyInsertionPosition(
  source: string,
  preferredPosition: number | null,
): number {
  const begin = source.lastIndexOf("\\begin{document}");
  const end = source.lastIndexOf("\\end{document}");
  if (end < 0 || begin < 0 || end <= begin) return end >= 0 ? end : source.length;
  const bodyStart = begin + "\\begin{document}".length;
  if (preferredPosition !== null && preferredPosition >= bodyStart && preferredPosition <= end) {
    return preferredPosition;
  }
  return end;
}
