export type ProjectSectionView =
  | "home"
  | "documents"
  | "papers"
  | "collections"
  | "notes"
  | "latex"
  | "assistant";

type ShortcutKeyInput = {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  defaultPrevented?: boolean;
};

export type GlobalShortcutAction =
  | { type: "search" }
  | { type: "new-note" }
  | { type: "upload" }
  | { type: "section"; view: ProjectSectionView };

const PROJECT_SECTIONS: readonly ProjectSectionView[] = [
  "home",
  "documents",
  "papers",
  "collections",
  "notes",
  "latex",
  "assistant",
];

export function resolveGlobalShortcut(
  event: ShortcutKeyInput,
  blockedContext: boolean,
): GlobalShortcutAction | null {
  if (blockedContext || event.defaultPrevented || event.repeat || event.isComposing) return null;

  const key = event.key.toLowerCase();
  const hasPrimaryModifier = Boolean(event.ctrlKey || event.metaKey);
  if (hasPrimaryModifier && !event.altKey && !event.shiftKey && key === "k") {
    return { type: "search" };
  }
  if (hasPrimaryModifier && event.altKey && !event.shiftKey) {
    if (key === "n") return { type: "new-note" };
    if (key === "u") return { type: "upload" };
    if (/^[1-7]$/.test(key)) {
      const view = PROJECT_SECTIONS[Number(key) - 1];
      if (view) return { type: "section", view };
    }
  }
  return null;
}
