type TextSelection<TNode> = {
  isCollapsed: boolean;
  rangeCount: number;
  anchorNode: TNode | null;
  focusNode: TNode | null;
  toString: () => string;
};

export function selectedTextWithin<TNode>(
  container: { contains: (node: TNode | null) => boolean },
  selection: TextSelection<TNode> | null,
): string | null {
  if (
    !selection
    || selection.isCollapsed
    || selection.rangeCount === 0
    || !selection.anchorNode
    || !selection.focusNode
    || !container.contains(selection.anchorNode)
    || !container.contains(selection.focusNode)
  ) return null;

  const text = selection.toString();
  return text.trim() ? text : null;
}
