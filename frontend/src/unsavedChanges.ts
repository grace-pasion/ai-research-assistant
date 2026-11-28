export function confirmUnsavedEditorLeave(hasUnsavedChanges: boolean): boolean {
  return !hasUnsavedChanges || window.confirm(
    "You have unsaved changes in Writing & analysis. Leave anyway? Your changes may be lost.",
  );
}

export function preventUnloadWithUnsavedChanges(
  event: Pick<BeforeUnloadEvent, "preventDefault"> & { returnValue: string },
  hasUnsavedChanges: boolean,
) {
  if (!hasUnsavedChanges) return;
  event.preventDefault();
  event.returnValue = "You have unsaved changes.";
}
