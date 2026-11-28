import { Copy } from "lucide-react";
import { useState } from "react";
import { copyTextToClipboard } from "./paperCitation";

type Props = {
  details: string;
};

export function CopyErrorDetailsButton({ details }: Props) {
  const [feedback, setFeedback] = useState<{
    details: string;
    status: "copying" | "copied" | "unavailable" | "failed";
  } | null>(null);
  const currentFeedback = feedback?.details === details ? feedback.status : null;

  async function copyDetails() {
    setFeedback({ details, status: "copying" });
    try {
      await copyTextToClipboard(details);
      setFeedback({ details, status: "copied" });
    } catch (cause) {
      setFeedback({
        details,
        status: cause instanceof Error
          && cause.message === "Clipboard access is unavailable in this browser."
          ? "unavailable"
          : "failed",
      });
    }
  }

  return (
    <span className="copy-error-details">
      <button
        type="button"
        className="button secondary small-button copy-error-details-button"
        disabled={!details.trim() || currentFeedback === "copying"}
        onClick={() => void copyDetails()}
      >
        <Copy size={13} aria-hidden="true" />
        Copy error details
      </button>
      {currentFeedback === "copying" && <span className="copy-error-details-feedback" role="status">Copying…</span>}
      {currentFeedback === "copied" && <span className="copy-error-details-feedback" role="status">Error details copied.</span>}
      {currentFeedback === "unavailable" && (
        <span className="copy-error-details-feedback error" role="alert">
          Clipboard access is unavailable in this browser.
        </span>
      )}
      {currentFeedback === "failed" && (
        <span className="copy-error-details-feedback error" role="alert">
          Could not copy error details. Check browser clipboard permissions and try again.
        </span>
      )}
    </span>
  );
}
