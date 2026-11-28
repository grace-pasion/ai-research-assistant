export function hasFileDragType(types: ArrayLike<string>): boolean {
  return Array.from(types).includes("Files");
}

export function getDroppedFiles(dataTransfer: { files: ArrayLike<File> }): File[] {
  return Array.from(dataTransfer.files);
}
