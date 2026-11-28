import { useRef, useState, type DragEvent } from "react";
import { Upload } from "lucide-react";
import { getDroppedFiles, hasFileDragType } from "./documentFileDrop";

type DocumentUploadDropzoneProps = {
  disabled: boolean;
  onFiles: (files: File[]) => void;
};

export function DocumentUploadDropzone({
  disabled,
  onFiles,
}: DocumentUploadDropzoneProps) {
  const [draggingFiles, setDraggingFiles] = useState(false);
  const dragDepth = useRef(0);

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    if (!hasFileDragType(event.dataTransfer.types)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDraggingFiles(!disabled);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!hasFileDragType(event.dataTransfer.types)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = disabled ? "none" : "copy";
  }

  function handleDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDraggingFiles(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    const files = getDroppedFiles(event.dataTransfer);
    if (!files.length) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDraggingFiles(false);
    if (!disabled) onFiles(files);
  }

  return (
    <div
      className={`document-upload-dropzone${draggingFiles ? " is-active" : ""}${disabled ? " is-disabled" : ""}`}
      role="region"
      aria-label="Document upload drop area"
      aria-disabled={disabled}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <Upload size={19} aria-hidden="true" />
      <strong>{draggingFiles ? "Drop files to upload" : "Drag files here to upload"}</strong>
      <span>
        {disabled
          ? "Wait for the current upload to finish before adding more."
          : "PDF, DOCX, TXT, or Markdown · Up to 20 files"}
      </span>
    </div>
  );
}
