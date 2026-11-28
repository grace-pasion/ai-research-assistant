import { Activity, AlertCircle, CheckCircle2, LoaderCircle } from "lucide-react";
import { useState } from "react";
import { CopyErrorDetailsButton } from "./CopyErrorDetailsButton";
import type { WorkStatusItem } from "./workStatus";

type Props = {
  items: WorkStatusItem[];
  projectName: string;
};

const KIND_LABELS: Record<WorkStatusItem["kind"], string> = {
  upload: "Upload",
  document: "Document",
  latex: "LaTeX",
};

export function WorkStatusPanel({ items, projectName }: Props) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;

  const activeCount = items.filter((item) => item.state === "active").length;
  const attentionCount = items.filter((item) => item.state === "attention").length;
  const visibleItems = items.slice(0, 8);
  const hiddenCount = items.length - visibleItems.length;
  const accessibleSummary = [
    activeCount ? `${activeCount} in progress` : null,
    attentionCount ? `${attentionCount} need attention` : null,
    !activeCount && !attentionCount ? `${items.length} recent result${items.length === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(", ");

  return (
    <div
      className="work-status-control"
      onKeyDown={(event) => {
        if (event.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        className="icon-button topbar-action work-status-button"
        aria-label={`Work status: ${accessibleSummary}`}
        aria-expanded={open}
        aria-controls="work-status-panel"
        title={`Work status: ${accessibleSummary}`}
        onClick={() => setOpen((current) => !current)}
      >
        {activeCount ? (
          <LoaderCircle size={16} className="spin" aria-hidden="true" />
        ) : attentionCount ? (
          <AlertCircle size={16} aria-hidden="true" />
        ) : (
          <Activity size={16} aria-hidden="true" />
        )}
        <span className="work-status-button-label">Work</span>
        {activeCount > 0 && <span className="work-status-count">{activeCount}</span>}
        {attentionCount > 0 && <span className="work-status-attention-count">{attentionCount}</span>}
      </button>
      <section
        id="work-status-panel"
        className="work-status-popover"
        role="region"
        aria-label="Work status"
        hidden={!open}
      >
          <div className="work-status-heading">
            <div>
              <strong>Work status</strong>
              <span>{projectName}</span>
            </div>
            <span aria-live="polite">{accessibleSummary}</span>
          </div>
          <ul className="work-status-list">
            {visibleItems.map((item) => (
              <li className={`work-status-item ${item.state}`} key={item.id}>
                <span className="work-status-item-icon" aria-hidden="true">
                  {item.state === "active" ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : item.state === "attention" ? (
                    <AlertCircle size={15} />
                  ) : (
                    <CheckCircle2 size={15} />
                  )}
                </span>
                <div className="work-status-item-copy">
                  <strong>{item.title}</strong>
                  <span>{KIND_LABELS[item.kind]} · {item.statusLabel}</span>
                  {item.detail && <p>{item.detail}</p>}
                  {item.state === "attention" && (
                    <CopyErrorDetailsButton
                      details={[
                        `Title: ${item.title}`,
                        `Type: ${KIND_LABELS[item.kind]}`,
                        `Status: ${item.statusLabel}`,
                        `Details: ${item.detail ?? "No additional details were provided."}`,
                      ].join("\n")}
                    />
                  )}
                </div>
              </li>
            ))}
          </ul>
          {hiddenCount > 0 && (
            <p className="work-status-more">And {hiddenCount} more item{hiddenCount === 1 ? "" : "s"}.</p>
          )}
      </section>
    </div>
  );
}
