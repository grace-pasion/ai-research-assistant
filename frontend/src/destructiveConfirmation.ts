export type DestructiveActionVerb = "Cancel" | "Delete" | "Remove";

export function confirmDestructiveAction(
  action: DestructiveActionVerb,
  itemName: string,
  consequence: string,
): boolean {
  return window.confirm(`${action} “${itemName}”? ${consequence}`);
}
