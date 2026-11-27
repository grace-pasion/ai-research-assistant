import { X } from "lucide-react";

type Props = {
  filename: string;
  versionNumber: number;
  createdAt: string;
  previousContent: string;
  currentContent: string | null;
  onClose: () => void;
};

function VersionContent({ content }: { content: string }) {
  return content ? <pre>{content}</pre> : <p className="workspace-comparison-empty">Empty file</p>;
}

export function WorkspaceVersionComparison({
  filename,
  versionNumber,
  createdAt,
  previousContent,
  currentContent,
  onClose,
}: Props) {
  return (
    <section
      className="workspace-comparison"
      aria-label={`Compare ${filename} version ${versionNumber}`}
    >
      <div className="workspace-history-heading">
        <strong>Comparing {filename} · version {versionNumber}</strong>
        <button
          type="button"
          className="workspace-comparison-close"
          aria-label="Close version comparison"
          onClick={onClose}
        >
          <X size={14} />
        </button>
      </div>
      <div className="workspace-comparison-columns">
        <section>
          <h4>Earlier version</h4>
          <small>{new Date(createdAt).toLocaleString()}</small>
          <VersionContent content={previousContent} />
        </section>
        <section>
          <h4>Current working copy</h4>
          {currentContent === null
            ? <p className="workspace-comparison-empty">This file is not in the current workspace.</p>
            : <VersionContent content={currentContent} />}
        </section>
      </div>
    </section>
  );
}
