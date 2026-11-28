import { useState } from "react";
import type { Paper, PaperStudyExtraction } from "./types";
import {
  hasStudyExtractionChanges,
  STUDY_EXTRACTION_FIELDS,
  studyExtractionValues,
  type StudyExtractionValues,
} from "./studyExtraction";

type Props = {
  papers: Paper[];
  canEdit: boolean;
  onSave: (
    paperId: string,
    values: StudyExtractionValues,
    expectedUpdatedAt: string | null,
  ) => Promise<PaperStudyExtraction>;
};

export function StudyExtractionTable({ papers, canEdit, onSave }: Props) {
  const [drafts, setDrafts] = useState<Record<string, StudyExtractionValues>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savingPaperId, setSavingPaperId] = useState<string | null>(null);

  function draftFor(paper: Paper): StudyExtractionValues {
    return drafts[paper.paper_id] ?? studyExtractionValues(paper.study_extraction);
  }

  function updateDraft(paper: Paper, field: keyof StudyExtractionValues, value: string) {
    setDrafts((current) => ({
      ...current,
      [paper.paper_id]: {
        ...(current[paper.paper_id] ?? studyExtractionValues(paper.study_extraction)),
        [field]: value,
      },
    }));
    setErrors((current) => {
      if (!(paper.paper_id in current)) return current;
      const next = { ...current };
      delete next[paper.paper_id];
      return next;
    });
  }

  async function save(paper: Paper) {
    const values = draftFor(paper);
    setSavingPaperId(paper.paper_id);
    setErrors((current) => {
      const next = { ...current };
      delete next[paper.paper_id];
      return next;
    });
    try {
      await onSave(paper.paper_id, values, paper.study_extraction?.updated_at ?? null);
      setDrafts((current) => {
        const next = { ...current };
        delete next[paper.paper_id];
        return next;
      });
    } catch (cause) {
      setErrors((current) => ({
        ...current,
        [paper.paper_id]: cause instanceof Error
          ? cause.message
          : "Could not save this study extraction.",
      }));
    } finally {
      setSavingPaperId(null);
    }
  }

  function discard(paperId: string) {
    setDrafts((current) => {
      const next = { ...current };
      delete next[paperId];
      return next;
    });
    setErrors((current) => {
      const next = { ...current };
      delete next[paperId];
      return next;
    });
  }

  return (
    <section className="study-extraction" aria-labelledby="study-extraction-title">
      <div className="study-extraction-heading">
        <div>
          <h3 id="study-extraction-title">Study extraction matrix</h3>
          <p>Shared project values, with one row per saved paper.</p>
        </div>
        {!canEdit && <span className="study-extraction-readonly">Read-only access</span>}
      </div>
      {papers.length === 0 ? (
        <p className="muted compact">
          {canEdit
            ? "Search above and save a paper, or import a bibliography, to begin shared study extraction."
            : "Ask a project editor to save or import papers before study extraction can begin."}
        </p>
      ) : (
        <div className="study-extraction-scroll">
          <table className="study-extraction-table" aria-label="Study extraction table">
            <thead>
              <tr>
                <th scope="col">Paper</th>
                {STUDY_EXTRACTION_FIELDS.map((field) => (
                  <th scope="col" key={field.name}>{field.label}</th>
                ))}
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {papers.map((paper) => {
                const draft = draftFor(paper);
                const dirty = hasStudyExtractionChanges(draft, paper.study_extraction);
                const saving = savingPaperId === paper.paper_id;
                return (
                  <tr key={paper.paper_id}>
                    <th scope="row" className="study-extraction-paper">
                      <strong>{paper.title}</strong>
                      <span>
                        {paper.publication_year ?? "Year unavailable"}
                        {paper.doi ? ` · ${paper.doi}` : ""}
                      </span>
                    </th>
                    {STUDY_EXTRACTION_FIELDS.map((field) => (
                      <td key={field.name}>
                        <label className="study-extraction-cell">
                          <textarea
                            aria-label={`${field.label} for ${paper.title}`}
                            value={draft[field.name]}
                            maxLength={field.maxLength}
                            rows={3}
                            readOnly={!canEdit || saving}
                            onChange={(event) =>
                              updateDraft(paper, field.name, event.target.value)
                            }
                          />
                        </label>
                      </td>
                    ))}
                    <td className="study-extraction-actions">
                      {canEdit && (
                        <div className="study-extraction-buttons">
                          <button
                            className="button primary small-button"
                            onClick={() => void save(paper)}
                            disabled={!dirty || savingPaperId !== null}
                          >
                            {saving ? "Saving…" : "Save row"}
                          </button>
                          {dirty && (
                            <button
                              className="text-button"
                              onClick={() => discard(paper.paper_id)}
                              disabled={saving}
                            >
                              Discard
                            </button>
                          )}
                        </div>
                      )}
                      {paper.study_extraction ? (
                        <small>
                          Saved by {paper.study_extraction.updated_by_name ?? "a collaborator"} ·{" "}
                          <time dateTime={paper.study_extraction.updated_at}>
                            {new Date(paper.study_extraction.updated_at).toLocaleString()}
                          </time>
                        </small>
                      ) : (
                        <small>Not yet extracted</small>
                      )}
                      {errors[paper.paper_id] && (
                        <span className="study-extraction-error" role="alert">
                          {errors[paper.paper_id]}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
