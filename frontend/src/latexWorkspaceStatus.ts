export type WorkspaceSaveStatus = "saved" | "unsaved" | "saving" | "error";

export function getWorkspaceSaveStatusLabel(
  status: WorkspaceSaveStatus,
  updatedAt: string | null,
): string {
  if (status === "saving") return "Saving…";
  if (status === "unsaved") return "Unsaved changes";
  if (status === "error") return "Save failed";
  return updatedAt ? "Saved" : "Not saved yet";
}

export function formatLastSavedAt(updatedAt: string | null): string | null {
  if (!updatedAt) return null;
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}
