export type MentionQuery = {
  start: number;
  end: number;
  query: string;
};

export function getMentionQuery(value: string, cursor: number): MentionQuery | null {
  const beforeCursor = value.slice(0, cursor);
  const match = /(^|[^A-Za-z0-9_@])@([A-Za-z0-9._-]*)$/.exec(beforeCursor);
  if (!match) return null;
  const start = cursor - match[0].length + match[1].length;
  return { start, end: cursor, query: match[2] };
}

export function insertMention(
  value: string,
  cursor: number,
  username: string,
): { value: string; cursor: number } {
  const mention = getMentionQuery(value, cursor);
  if (!mention) return { value, cursor };
  const insertion = `@${username} `;
  return {
    value: `${value.slice(0, mention.start)}${insertion}${value.slice(mention.end)}`,
    cursor: mention.start + insertion.length,
  };
}
