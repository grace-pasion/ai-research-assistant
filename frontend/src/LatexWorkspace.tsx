import {
  BookOpen,
  Check,
  Code2,
  Download,
  Eye,
  FileCode2,
  FileText,
  Library,
  LoaderCircle,
  Save,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DocumentRecord, Paper, Project } from "./types";
import { parseLatexPreview } from "./latexPreview";

type WorkspaceFiles = {
  main_tex: string;
  references_bib: string;
};

type WorkspaceRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type Props = {
  project: Project;
  documents: DocumentRecord[];
  papers: Paper[];
  request: WorkspaceRequest;
};

type EditorFile = "main.tex" | "references.bib";
type PaneMode = "split" | "source" | "preview";

const EMPTY_WORKSPACE: WorkspaceFiles = { main_tex: "", references_bib: "" };

function encodeLatex(value: string): string {
  const escaped: Record<string, string> = {
    "\\": "\\textbackslash{}",
    "#": "\\#",
    "$": "\\$",
    "%": "\\%",
    "&": "\\&",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "^": "\\textasciicircum{}",
    "~": "\\textasciitilde{}",
  };
  return Array.from(value, (character) => escaped[character] ?? character).join("");
}

function encodeBibtex(value: string): string {
  return value.replace(/[{}]/g, "").replace(/\\/g, "");
}

function citationKey(paper: Paper): string {
  const surname = paper.authors[0]?.author_name.split(/\s+/).pop() ?? "paper";
  const author = surname.toLowerCase().replace(/[^a-z0-9]/g, "") || "paper";
  const id = paper.paper_id.replace(/-/g, "").slice(0, 6).toLowerCase();
  return `${author}${paper.publication_year ?? "nd"}${id}`;
}

function bibtexEntry(paper: Paper): string {
  const key = citationKey(paper);
  const authors = paper.authors.map((author) => encodeBibtex(author.author_name)).join(" and ");
  const fields = [
    `  title = {${encodeBibtex(paper.title)}}`,
    ...(authors ? [`  author = {${authors}}`] : []),
    ...(paper.publication_year ? [`  year = {${paper.publication_year}}`] : []),
    ...(paper.venue ? [`  journal = {${encodeBibtex(paper.venue)}}`] : []),
    ...(paper.doi ? [`  doi = {${encodeBibtex(paper.doi)}}`] : []),
  ];
  return `@article{${key},\n${fields.join(",\n")}\n}`;
}

function insertAtCursor(source: string, insertion: string, position: number): string {
  const at = Math.max(0, Math.min(position, source.length));
  const before = source.slice(0, at);
  const after = source.slice(at);
  const prefix = before && !/\s$/.test(before) ? "\n\n" : "";
  const suffix = after && !/^\s/.test(after) ? "\n\n" : "";
  return `${before}${prefix}${insertion}${suffix}${after}`;
}

function downloadText(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function LatexWorkspace({ project, documents, papers, request }: Props) {
  const [workspace, setWorkspace] = useState<WorkspaceFiles>(EMPTY_WORKSPACE);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeFile, setActiveFile] = useState<EditorFile>("main.tex");
  const [paneMode, setPaneMode] = useState<PaneMode>("split");
  const [saveStatus, setSaveStatus] = useState<"saved" | "unsaved" | "saving" | "error">("saved");
  const [workspaceError, setWorkspaceError] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [excerpts, setExcerpts] = useState<Record<string, string>>({});
  const [loadingExcerpt, setLoadingExcerpt] = useState<string | null>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const cursorPositionRef = useRef<number | null>(null);
  const workspaceRef = useRef(workspace);
  const savedContentRef = useRef("");
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoaded(false);
    setWorkspaceError("");
    request<WorkspaceFiles>(`/api/projects/${project.project_id}/latex`)
      .then((files) => {
        if (!active) return;
        workspaceRef.current = files;
        savedContentRef.current = JSON.stringify(files);
        setWorkspace(files);
        setLoaded(true);
        setSaveStatus("saved");
      })
      .catch((cause: unknown) => {
        if (active) setWorkspaceError(cause instanceof Error ? cause.message : "Could not load the LaTeX workspace.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project.project_id, request]);

  const persist = useCallback((snapshot: WorkspaceFiles) => {
    setSaveStatus("saving");
    const operation = saveQueueRef.current.catch(() => undefined).then(async () => {
      try {
        const saved = await request<WorkspaceFiles>(`/api/projects/${project.project_id}/latex`, {
          method: "PUT",
          body: JSON.stringify(snapshot),
        });
        if (!mountedRef.current) return;
        savedContentRef.current = JSON.stringify(saved);
        setSaveStatus(JSON.stringify(workspaceRef.current) === savedContentRef.current ? "saved" : "unsaved");
        setWorkspaceError("");
      } catch (cause) {
        if (!mountedRef.current) return;
        setSaveStatus("error");
        setWorkspaceError(cause instanceof Error ? cause.message : "Could not save the LaTeX workspace.");
      }
    });
    saveQueueRef.current = operation;
    return operation;
  }, [project.project_id, request]);

  useEffect(() => {
    if (!loaded || saveStatus !== "unsaved") return;
    const timer = window.setTimeout(() => void persist(workspace), 700);
    return () => window.clearTimeout(timer);
  }, [loaded, persist, saveStatus, workspace]);

  const preview = useMemo(() => parseLatexPreview(workspace.main_tex), [workspace.main_tex]);
  const currentValue = activeFile === "main.tex" ? workspace.main_tex : workspace.references_bib;

  function updateFile(value: string) {
    const updated = {
      ...workspaceRef.current,
      [activeFile === "main.tex" ? "main_tex" : "references_bib"]: value,
    };
    workspaceRef.current = updated;
    setWorkspace(updated);
    setSaveStatus(JSON.stringify(updated) === savedContentRef.current ? "saved" : "unsaved");
  }

  function insertIntoMain(insertion: string) {
    const textarea = editorRef.current;
    const source = workspaceRef.current.main_tex;
    const position = activeFile === "main.tex" && textarea && cursorPositionRef.current !== null
      ? cursorPositionRef.current
      : Math.max(0, source.lastIndexOf("\\end{document}"));
    const updated = { ...workspaceRef.current, main_tex: insertAtCursor(source, insertion, position) };
    workspaceRef.current = updated;
    setWorkspace(updated);
    setActiveFile("main.tex");
    setSaveStatus("unsaved");
    window.setTimeout(() => {
      editorRef.current?.focus();
      editorRef.current?.setSelectionRange(position + insertion.length + 2, position + insertion.length + 2);
      cursorPositionRef.current = position + insertion.length + 2;
    }, 0);
  }

  function citePaper(paper: Paper, includeAbstract = false) {
    const key = citationKey(paper);
    const existing = workspaceRef.current.references_bib;
    const entry = bibtexEntry(paper);
    const references = existing.includes(`{${key},`) ? existing : `${existing.trimEnd()}${existing.trim() ? "\n\n" : ""}${entry}\n`;
    const abstract = paper.abstract?.replace(/<[^>]*>/g, "").trim();
    const citation = includeAbstract && abstract
      ? `\\begin{quote}\n${encodeLatex(abstract)}\n\\end{quote}\n\\cite{${key}}`
      : `\\cite{${key}}`;
    workspaceRef.current = { ...workspaceRef.current, references_bib: references };
    setWorkspace(workspaceRef.current);
    insertIntoMain(citation);
  }

  async function loadDocumentExcerpt(document: DocumentRecord) {
    setLoadingExcerpt(document.document_id);
    setSourceError("");
    try {
      const reader = await request<{ text: string }>(`/api/documents/${document.document_id}/reader`);
      if (!reader.text.trim()) {
        setSourceError(`${document.filename} does not contain extracted text yet.`);
        return;
      }
      setExcerpts((current) => ({
        ...current,
        [document.document_id]: reader.text.slice(0, 2000),
      }));
    } catch (cause) {
      setSourceError(cause instanceof Error ? cause.message : "Could not load document text.");
    } finally {
      setLoadingExcerpt(null);
    }
  }

  function insertDocumentExcerpt(document: DocumentRecord) {
    const excerpt = excerpts[document.document_id]?.trim();
    if (!excerpt) return;
    insertIntoMain(
      `\\begin{quote}\n${encodeLatex(excerpt)}\n\\end{quote}\n\\noindent\\textit{Source: ${encodeLatex(document.filename)}}`,
    );
  }

  return (
    <section className="latex-workspace section-content" aria-label="LaTeX main document workspace">
      <header className="latex-header">
        <div>
          <p className="eyebrow">PROJECT WRITING</p>
          <h2>Main document</h2>
          <p>Write in LaTeX and bring saved papers and document excerpts into your draft.</p>
        </div>
        <div className="latex-header-actions">
          <span className={`latex-save-status ${saveStatus}`} role="status">
            {saveStatus === "saving" ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}
            {saveStatus === "saving" ? "Saving…" : saveStatus === "unsaved" ? "Unsaved changes" : saveStatus === "error" ? "Save failed" : "Saved"}
          </span>
          <button
            type="button"
            className="button secondary small-button"
            onClick={() => downloadText(activeFile, currentValue)}
            disabled={loading}
          >
            <Download size={14} /> Download {activeFile}
          </button>
          <button
            type="button"
            className="button primary small-button"
            onClick={() => void persist(workspace)}
            disabled={loading || !loaded || saveStatus === "saving" || saveStatus === "saved"}
          >
            <Save size={14} /> Save now
          </button>
        </div>
      </header>
      {workspaceError && <p className="inline-error latex-error" role="alert">{workspaceError}</p>}
      {loading ? (
        <div className="latex-loading"><LoaderCircle className="spin" size={18} /> Loading project files…</div>
      ) : (
        <div className="latex-layout">
          <aside className="latex-sources">
            <div className="latex-files">
              <span className="latex-label">PROJECT FILES</span>
              <button type="button" className={`latex-file ${activeFile === "main.tex" ? "active" : ""}`} onClick={() => setActiveFile("main.tex")}>
                <FileCode2 size={15} /> main.tex
              </button>
              <button type="button" className={`latex-file ${activeFile === "references.bib" ? "active" : ""}`} onClick={() => setActiveFile("references.bib")}>
                <BookOpen size={15} /> references.bib
              </button>
            </div>
            <div className="latex-source-group">
              <div className="latex-group-heading"><Library size={14} /><span>SAVED LITERATURE</span><small>{papers.length}</small></div>
              {papers.length ? papers.map((paper) => (
                <article className="latex-source-card" key={paper.paper_id}>
                  <strong>{paper.title}</strong>
                  <span>{paper.authors[0]?.author_name ?? "Unknown author"} · {paper.publication_year ?? "n.d."}</span>
                  <div className="latex-source-actions">
                    <button type="button" onClick={() => citePaper(paper)} title={`Add ${citationKey(paper)} to references.bib and cite it`}>
                      <Code2 size={12} /> Cite
                    </button>
                    {paper.abstract && (
                      <button type="button" onClick={() => citePaper(paper, true)} title="Insert the abstract with its citation">
                        <Upload size={12} /> Abstract
                      </button>
                    )}
                  </div>
                </article>
              )) : <p className="latex-empty">Save papers in Literature to cite them here.</p>}
            </div>
            <div className="latex-source-group">
              <div className="latex-group-heading"><FileText size={14} /><span>PROJECT DOCUMENTS</span><small>{documents.length}</small></div>
              {documents.length ? documents.map((document) => (
                <details className="latex-document-source" key={document.document_id}>
                  <summary>{document.filename}<small>{document.processing_status === "ready" ? "Ready" : document.processing_status.replace(/_/g, " ")}</small></summary>
                  {document.processing_status === "ready" ? (
                    excerpts[document.document_id] === undefined ? (
                      <button
                        type="button"
                        className="latex-load-excerpt"
                        disabled={loadingExcerpt === document.document_id}
                        onClick={() => void loadDocumentExcerpt(document)}
                      >
                        {loadingExcerpt === document.document_id ? <LoaderCircle size={12} className="spin" /> : <Upload size={12} />}
                        Load editable excerpt
                      </button>
                    ) : (
                      <>
                        <textarea
                          aria-label={`Excerpt from ${document.filename}`}
                          value={excerpts[document.document_id]}
                          maxLength={4000}
                          rows={5}
                          onChange={(event) => setExcerpts((current) => ({
                            ...current,
                            [document.document_id]: event.target.value,
                          }))}
                        />
                        <button type="button" className="latex-insert-excerpt" onClick={() => insertDocumentExcerpt(document)}>
                          Insert excerpt
                        </button>
                      </>
                    )
                  ) : <p className="latex-empty">Wait for document text extraction to finish.</p>}
                </details>
              )) : <p className="latex-empty">Upload or import documents in Documents to use their text here.</p>}
              {sourceError && <p className="inline-error latex-error" role="alert">{sourceError}</p>}
            </div>
          </aside>
          <div className="latex-editor-panel">
            <div className="latex-toolbar">
              <span className="latex-current-file"><FileCode2 size={15} />{activeFile}</span>
              <div className="latex-view-toggle" role="group" aria-label="Editor layout">
                <button type="button" className={paneMode === "source" ? "active" : ""} onClick={() => setPaneMode("source")} aria-pressed={paneMode === "source"} title="Source only">
                  <Code2 size={14} /><span>Source</span>
                </button>
                <button type="button" className={paneMode === "split" ? "active" : ""} onClick={() => setPaneMode("split")} aria-pressed={paneMode === "split"} title="Source and preview">
                  <BookOpen size={14} /><span>Split</span>
                </button>
                <button type="button" className={paneMode === "preview" ? "active" : ""} onClick={() => setPaneMode("preview")} aria-pressed={paneMode === "preview"} title="Preview only">
                  <Eye size={14} /><span>Preview</span>
                </button>
              </div>
            </div>
            <div className={`latex-panes mode-${paneMode}`}>
              {paneMode !== "preview" && (
                <div className="latex-source-pane">
                  <div className="latex-editor-caption"><Code2 size={13} /> LaTeX source</div>
                  <textarea
                    ref={editorRef}
                    aria-label={`${activeFile} source`}
                    autoCapitalize="off"
                    autoComplete="off"
                    autoCorrect="off"
                    spellCheck={false}
                    value={currentValue}
                    onChange={(event) => {
                      cursorPositionRef.current = event.currentTarget.selectionStart;
                      updateFile(event.currentTarget.value);
                    }}
                    onClick={(event) => {
                      cursorPositionRef.current = event.currentTarget.selectionStart;
                    }}
                    onKeyUp={(event) => {
                      cursorPositionRef.current = event.currentTarget.selectionStart;
                    }}
                  />
                </div>
              )}
              {paneMode !== "source" && (
                <div className="latex-preview-pane">
                  <div className="latex-editor-caption"><Eye size={13} /> {activeFile === "main.tex" ? "Live article preview" : "Bibliography source"}</div>
                  {activeFile === "main.tex" ? (
                    <article className="latex-paper-preview">
                      {preview.title && <h1>{preview.title}</h1>}
                      {preview.author && <p className="latex-preview-author">{preview.author}</p>}
                      {preview.blocks.map((block, index) => {
                        if (block.type === "section") return <h2 key={index}>{block.text}</h2>;
                        if (block.type === "subsection") return <h3 key={index}>{block.text}</h3>;
                        return <p key={index}>{block.text}</p>;
                      })}
                      {!preview.blocks.length && <p className="latex-empty">Your article preview will appear here as you write.</p>}
                    </article>
                  ) : (
                    <pre className="latex-bib-preview">{workspace.references_bib || "% Add citations from saved literature to build this bibliography."}</pre>
                  )}
                  <p className="latex-preview-note">Live preview for common article structure; this is not a full TeX compiler.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
