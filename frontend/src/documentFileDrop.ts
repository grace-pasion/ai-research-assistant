const UPLOAD_FILE_TYPE_LABELS: Record<string, string> = {
  pdf: "PDF",
  docx: "Word document (DOCX)",
  txt: "Text file (TXT)",
  md: "Markdown (MD)",
};

export function hasFileDragType(types: ArrayLike<string>): boolean {
  return Array.from(types).includes("Files");
}

export function getDroppedFiles(dataTransfer: { files: ArrayLike<File> }): File[] {
  return Array.from(dataTransfer.files);
}

export function getUploadFileType(file: Pick<File, "name" | "type">): string {
  const extension = file.name.split(".").pop()?.toLowerCase();
  return UPLOAD_FILE_TYPE_LABELS[extension ?? ""] ?? (file.type || "Unknown");
}
