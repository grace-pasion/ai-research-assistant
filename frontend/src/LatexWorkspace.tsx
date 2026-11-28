import {
  AlertCircle,
  BookOpen,
  Check,
  Code2,
  Download,
  Eye,
  FileCode2,
  FileOutput,
  FileText,
  History,
  Library,
  LoaderCircle,
  Save,
  Upload,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { DocumentRecord, Paper, Project } from "./types";
import { parseLatexPreview } from "./latexPreview";
import {
  checkLatexCitationKeys,
  filterCitationPapers,
  findLatexBibliographyStyle,
  hasBibtexCitationKey,
  isValidLatexCitationStyleName,
  updateLatexBibliographyStyle,
} from "./latexCitations";
import { documentBodyInsertionPosition, insertAtCursor } from "./latexEditor";
import { WorkspaceVersionComparison } from "./WorkspaceVersionComparison";
import { fetchPdfObjectUrl } from "./api";
import { findLatexSourceLocation, sourceOffsetForLine } from "./latexDiagnostics";
import { formatLastSavedAt, getWorkspaceSaveStatusLabel } from "./latexWorkspaceStatus";
import {
  ensureLatexPackage,
  pythonOutputInsertion,
  pythonOutputPackage,
} from "./pythonWorkspace";
import type { LatexCompileActivity } from "./workStatus";

const PythonAnalysisWorkspace = lazy(async () => {
  const module = await import("./PythonAnalysisWorkspace");
  return { default: module.PythonAnalysisWorkspace };
});

type WorkspaceFiles = {
  main_tex: string;
  references_bib: string;
  updated_at: string | null;
};

type WorkspaceRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type WorkspaceVersion = {
  version_id: string;
  filename: EditorFile;
  version_number: number;
  created_at: string;
  author_name: string | null;
};

type WorkspaceVersionDetails = WorkspaceVersion & { content: string };

type Props = {
  project: Project;
  documents: DocumentRecord[];
  papers: Paper[];
  request: WorkspaceRequest;
  onCompileStatusChange: (activity: LatexCompileActivity) => void;
};

type EditorFile = "main.tex" | "references.bib";
type PaneMode = "split" | "source" | "preview" | "pdf";
type CitationStyle = "plainnat" | "abbrvnat" | "unsrtnat" | "apalike";
const CUSTOM_CITATION_STYLE = "custom";

const CITATION_STYLES: { value: CitationStyle; label: string }[] = [
  { value: "plainnat", label: "Natbib (author-year or numeric)" },
  { value: "abbrvnat", label: "Abbreviated author-year" },
  { value: "unsrtnat", label: "Numeric, citation order" },
  { value: "apalike", label: "APA-like author-date" },
];

const EMPTY_WORKSPACE: WorkspaceFiles = { main_tex: "", references_bib: "", updated_at: null };

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

function downloadText(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function LatexWorkspace({
  project,
  documents,
  papers,
  request,
  onCompileStatusChange,
}: Props) {
  const [workspace, setWorkspace] = useState<WorkspaceFiles>(EMPTY_WORKSPACE);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeFile, setActiveFile] = useState<EditorFile>("main.tex");
  const [pythonWorkspaceVisited, setPythonWorkspaceVisited] = useState(false);
  const [pythonWorkspaceActive, setPythonWorkspaceActive] = useState(false);
  const [pythonFiles, setPythonFiles] = useState<string[]>([]);
  const [selectedPythonFile, setSelectedPythonFile] = useState("main.py");
  const [paneMode, setPaneMode] = useState<PaneMode>("split");
  const [saveStatus, setSaveStatus] = useState<"saved" | "unsaved" | "saving" | "error">("saved");
  const [workspaceError, setWorkspaceError] = useState("");
  const [sourceError, setSourceError] = useState("");
  const [citationSearch, setCitationSearch] = useState("");
  const [customCitationStyleDraft, setCustomCitationStyleDraft] = useState("");
  const [customCitationStyleSelected, setCustomCitationStyleSelected] = useState(false);
  const [citationStyleError, setCitationStyleError] = useState("");
  const [compileError, setCompileError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyVersions, setHistoryVersions] = useState<WorkspaceVersion[]>([]);
  const [comparison, setComparison] = useState<WorkspaceVersionDetails | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [comparisonLoading, setComparisonLoading] = useState<string | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  const [restoringVersion, setRestoringVersion] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [excerpts, setExcerpts] = useState<Record<string, string>>({});
  const [loadingExcerpt, setLoadingExcerpt] = useState<string | null>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const cursorPositionRef = useRef<number | null>(null);
  const insertionSequenceRef = useRef(0);
  const workspaceRef = useRef(workspace);
  const savedContentRef = useRef("");
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const autosaveTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  const pdfUrlRef = useRef<string | null>(null);
  const canEdit = project.access_role === "owner" || project.access_role === "edit";

  async function loadHistory(filename: EditorFile) {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const versions = await request<WorkspaceVersion[]>(
        `/api/projects/${project.project_id}/latex/history`,
      );
      setHistoryVersions(versions.filter((version) => version.filename === filename));
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not load file history.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function compareVersion(version: WorkspaceVersion) {
    setComparisonLoading(version.version_id);
    setComparison(null);
    setComparisonError("");
    try {
      const details = await request<WorkspaceVersionDetails>(
        `/api/projects/${project.project_id}/latex/history/${version.version_id}`,
      );
      setComparison(details);
    } catch (cause) {
      setComparisonError(cause instanceof Error ? cause.message : "Could not load this file version.");
    } finally {
      setComparisonLoading(null);
    }
  }

  async function restoreVersion(version: WorkspaceVersion) {
    if (!window.confirm(
      `Restore ${version.filename} to version ${version.version_number}? This replaces the shared file and discards any unsaved edits.`,
    )) return;
    setRestoringVersion(version.version_id);
    setHistoryError("");
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    try {
      await saveQueueRef.current;
      const restored = await request<WorkspaceFiles>(
        `/api/projects/${project.project_id}/latex/history/${version.version_id}/restore`,
        {
          method: "POST",
          body: JSON.stringify({ expected_updated_at: workspaceRef.current.updated_at }),
        },
      );
      workspaceRef.current = restored;
      savedContentRef.current = JSON.stringify(restored);
      setWorkspace(restored);
      setSaveStatus("saved");
      setCompileError("");
      await loadHistory(version.filename);
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not restore this version.");
    } finally {
      setRestoringVersion(null);
    }
  }

  function openCompileLocation() {
    const location = findLatexSourceLocation(compileError);
    if (!location) return;
    const source = location.filename === "main.tex"
      ? workspaceRef.current.main_tex
      : workspaceRef.current.references_bib;
    const offset = sourceOffsetForLine(source, location.line);
    setPythonWorkspaceActive(false);
    setActiveFile(location.filename);
    setPaneMode("source");
    cursorPositionRef.current = offset;
    window.setTimeout(() => {
      editorRef.current?.focus();
      editorRef.current?.setSelectionRange(offset, offset);
    }, 0);
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
    };
  }, []);

  useEffect(() => {
    setActiveFile("main.tex");
    setPythonWorkspaceVisited(false);
    setPythonWorkspaceActive(false);
    setPythonFiles([]);
    setSelectedPythonFile("main.py");
    setHistoryOpen(false);
    setHistoryVersions([]);
    setHistoryLoading(false);
    setHistoryError("");
    setRestoringVersion(null);
  }, [project.project_id]);

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
          body: JSON.stringify({
            ...snapshot,
            expected_updated_at: workspaceRef.current.updated_at ?? snapshot.updated_at,
          }),
        });
        if (!mountedRef.current) return null;
        savedContentRef.current = JSON.stringify(saved);
        const current = { ...workspaceRef.current, updated_at: saved.updated_at };
        workspaceRef.current = current;
        setWorkspace(current);
        setSaveStatus(JSON.stringify(current) === savedContentRef.current ? "saved" : "unsaved");
        setWorkspaceError("");
        return saved;
      } catch (cause) {
        if (!mountedRef.current) return;
        setSaveStatus("error");
        setWorkspaceError(cause instanceof Error ? cause.message : "Could not save the LaTeX workspace.");
        return null;
      }
    });
    saveQueueRef.current = operation.then(() => undefined);
    return operation;
  }, [project.project_id, request]);

  useEffect(() => {
    if (!loaded || !canEdit || saveStatus !== "unsaved" || restoringVersion !== null) return;
    const timer = window.setTimeout(() => void persist(workspace), 700);
    autosaveTimerRef.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (autosaveTimerRef.current === timer) autosaveTimerRef.current = null;
    };
  }, [canEdit, loaded, persist, restoringVersion, saveStatus, workspace]);

  useEffect(() => {
    if (!loaded || saveStatus !== "saved") return;
    let active = true;
    const timer = window.setInterval(() => {
      request<WorkspaceFiles>(`/api/projects/${project.project_id}/latex`)
        .then((latest) => {
          if (!active || saveStatus !== "saved"
            || JSON.stringify(workspaceRef.current) !== savedContentRef.current
            || JSON.stringify(latest) === savedContentRef.current) return;
          workspaceRef.current = latest;
          savedContentRef.current = JSON.stringify(latest);
          setWorkspace(latest);
          setWorkspaceError("");
        })
        .catch((cause: unknown) => {
          if (active) setWorkspaceError(cause instanceof Error ? cause.message : "Could not sync the shared workspace.");
        });
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [loaded, project.project_id, request, saveStatus]);

  async function reloadWorkspace() {
    setLoading(true);
    setWorkspaceError("");
    try {
      const latest = await request<WorkspaceFiles>(`/api/projects/${project.project_id}/latex`);
      workspaceRef.current = latest;
      savedContentRef.current = JSON.stringify(latest);
      setWorkspace(latest);
      setSaveStatus("saved");
    } catch (cause) {
      setWorkspaceError(cause instanceof Error ? cause.message : "Could not reload the shared workspace.");
    } finally {
      setLoading(false);
    }
  }

  const preview = useMemo(() => parseLatexPreview(workspace.main_tex), [workspace.main_tex]);
  const citationIssues = useMemo(
    () => checkLatexCitationKeys(workspace.main_tex, workspace.references_bib),
    [workspace.main_tex, workspace.references_bib],
  );
  const activeCitationStyle = findLatexBibliographyStyle(workspace.main_tex);
  const builtInCitationStyle = CITATION_STYLES.find((style) => style.value === activeCitationStyle);
  const isBuiltInCitationStyle = Boolean(builtInCitationStyle);
  const hasCustomCitationStyle = Boolean(activeCitationStyle && !isBuiltInCitationStyle);
  const citationStyle = customCitationStyleSelected || hasCustomCitationStyle
    ? CUSTOM_CITATION_STYLE
    : builtInCitationStyle?.value ?? "plainnat";
  const citationPapers = useMemo(
    () => filterCitationPapers(papers, citationSearch),
    [papers, citationSearch],
  );
  const currentValue = activeFile === "main.tex" ? workspace.main_tex : workspace.references_bib;

  useEffect(() => {
    setCustomCitationStyleSelected(hasCustomCitationStyle);
    setCustomCitationStyleDraft(hasCustomCitationStyle ? activeCitationStyle ?? "" : "");
    setCitationStyleError("");
  }, [activeCitationStyle, hasCustomCitationStyle]);

  function updateFile(value: string) {
    if (!canEdit || restoringVersion !== null) return;
    const updated = {
      ...workspaceRef.current,
      [activeFile === "main.tex" ? "main_tex" : "references_bib"]: value,
    };
    workspaceRef.current = updated;
    setWorkspace(updated);
    setSaveStatus(JSON.stringify(updated) === savedContentRef.current ? "saved" : "unsaved");
  }

  function insertIntoMain(insertion: string) {
    if (!canEdit || restoringVersion !== null) return;
    const textarea = editorRef.current;
    const source = workspaceRef.current.main_tex;
    const preferredPosition = !pythonWorkspaceActive
      && activeFile === "main.tex"
      && paneMode !== "preview"
      && paneMode !== "pdf"
      && textarea
      ? cursorPositionRef.current
      : null;
    const position = documentBodyInsertionPosition(source, preferredPosition);
    const inserted = insertAtCursor(source, insertion, position);
    const updated = { ...workspaceRef.current, main_tex: inserted.source };
    workspaceRef.current = updated;
    setWorkspace(updated);
    setHistoryOpen(false);
    setPythonWorkspaceActive(false);
    setActiveFile("main.tex");
    setSaveStatus("unsaved");
    cursorPositionRef.current = inserted.cursorPosition;
    const sequence = ++insertionSequenceRef.current;
    window.setTimeout(() => {
      if (sequence !== insertionSequenceRef.current) return;
      editorRef.current?.focus();
      editorRef.current?.setSelectionRange(inserted.cursorPosition, inserted.cursorPosition);
    }, 0);
  }

  function insertPythonOutput(filename: string) {
    const insertion = pythonOutputInsertion(filename);
    if (!insertion) return;
    const packageName = pythonOutputPackage(filename);
    if (packageName) {
      const current = workspaceRef.current;
      const mainTex = ensureLatexPackage(current.main_tex, packageName);
      if (mainTex !== current.main_tex) {
        const cursorPosition = cursorPositionRef.current;
        const packagePosition = mainTex.indexOf(`\\usepackage{${packageName}}`);
        if (
          !pythonWorkspaceActive
          && activeFile === "main.tex"
          && cursorPosition !== null
          && packagePosition <= cursorPosition
        ) {
          cursorPositionRef.current = cursorPosition + mainTex.length - current.main_tex.length;
        }
        workspaceRef.current = { ...current, main_tex: mainTex };
        setWorkspace(workspaceRef.current);
        setSaveStatus("unsaved");
      }
    }
    insertIntoMain(insertion);
  }

  function citePaper(paper: Paper, includeAbstract = false) {
    if (!canEdit || restoringVersion !== null) return;
    const key = citationKey(paper);
    const existing = workspaceRef.current.references_bib;
    const entry = bibtexEntry(paper);
    const references = hasBibtexCitationKey(existing, key)
      ? existing
      : `${existing.trimEnd()}${existing.trim() ? "\n\n" : ""}${entry}\n`;
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

  function openPythonWorkspace(filename = selectedPythonFile) {
    setHistoryOpen(false);
    setPythonWorkspaceVisited(true);
    setPythonWorkspaceActive(true);
    setSelectedPythonFile(filename);
  }

  function insertDocumentExcerpt(document: DocumentRecord) {
    if (!canEdit || restoringVersion !== null) return;
    const excerpt = excerpts[document.document_id]?.trim();
    if (!excerpt) return;
    insertIntoMain(
      `\\begin{quote}\n${encodeLatex(excerpt)}\n\\end{quote}\n\\noindent\\textit{Source: ${encodeLatex(document.filename)}}`,
    );
  }

  function changeCitationStyle(style: string) {
    if (!isValidLatexCitationStyleName(style)) {
      setCitationStyleError("Use letters, numbers, periods, underscores, or hyphens in the style name.");
      return;
    }
    if (!canEdit || restoringVersion !== null) return;
    const source = workspaceRef.current.main_tex;
    const updatedSource = updateLatexBibliographyStyle(source, style);
    const updated = { ...workspaceRef.current, main_tex: updatedSource };
    workspaceRef.current = updated;
    setWorkspace(updated);
    setSaveStatus(JSON.stringify(updated) === savedContentRef.current ? "saved" : "unsaved");
    setCitationStyleError("");
  }

  function applyCustomCitationStyle() {
    changeCitationStyle(customCitationStyleDraft.trim());
  }

  async function compilePdf() {
    setCompiling(true);
    setCompileError("");
    onCompileStatusChange({ status: "compiling", message: null });
    try {
      const saved = await persist(workspaceRef.current);
      if (!saved) {
        const message = "Save the latest changes before compiling.";
        if (mountedRef.current) setCompileError(message);
        onCompileStatusChange({ status: "failed", message });
        return;
      }
      const nextUrl = await fetchPdfObjectUrl(
        `/api/projects/${project.project_id}/latex/compile`,
        { method: "POST" },
      );
      if (!mountedRef.current) {
        URL.revokeObjectURL(nextUrl);
        onCompileStatusChange({ status: "completed", message: null });
        return;
      }
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
      pdfUrlRef.current = nextUrl;
      setPdfUrl(nextUrl);
      setPaneMode("pdf");
      onCompileStatusChange({ status: "completed", message: null });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not compile this document.";
      if (mountedRef.current) setCompileError(message);
      onCompileStatusChange({ status: "failed", message });
    } finally {
      if (mountedRef.current) setCompiling(false);
    }
  }

  const compileLocation = findLatexSourceLocation(compileError);
  const lastSavedAt = formatLastSavedAt(workspace.updated_at);
  const saveStatusClass = saveStatus === "saved" && !workspace.updated_at ? "unsaved" : saveStatus;

  return (
    <section className="latex-workspace section-content" aria-label="LaTeX main document workspace">
      <header className="latex-header">
        <div>
          <p className="eyebrow">PROJECT WRITING</p>
          <h2>Main document</h2>
          <p>Write in LaTeX and bring saved papers and document excerpts into your draft.</p>
        </div>
        <div className="latex-header-actions">
          <span className="latex-access-role">
            {{ owner: "Owner", read: "Reader", comment: "Commenter", edit: "Editor" }[project.access_role]} access
          </span>
          {!pythonWorkspaceActive && (
            <>
              {loaded && (
                <>
                  <span className={`latex-save-status ${saveStatusClass}`} role="status">
                    {saveStatus === "saving"
                      ? <LoaderCircle size={13} className="spin" />
                      : saveStatusClass === "unsaved" || saveStatus === "error"
                        ? <AlertCircle size={13} />
                        : <Check size={13} />}
                    {getWorkspaceSaveStatusLabel(saveStatus, workspace.updated_at)}
                  </span>
                  {workspace.updated_at !== null && (
                    <span className="latex-last-saved">
                      Last saved{" "}
                      {lastSavedAt
                        ? <time dateTime={workspace.updated_at}>{lastSavedAt}</time>
                        : "time unavailable"}
                    </span>
                  )}
                </>
              )}
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
                className="button secondary small-button"
                onClick={() => {
                  setHistoryOpen((open) => !open);
                  if (!historyOpen) void loadHistory(activeFile);
                }}
                disabled={loading || !loaded}
                aria-expanded={historyOpen}
              >
                <History size={14} /> History
              </button>
            </>
          )}
          <button
            type="button"
            className="button primary small-button"
            onClick={() => void compilePdf()}
            disabled={loading || !loaded || compiling || saveStatus === "saving" || restoringVersion !== null}
          >
            {compiling ? <LoaderCircle size={14} className="spin" /> : <FileOutput size={14} />}
            {compiling ? "Compiling…" : "Compile PDF"}
          </button>
          {canEdit && !pythonWorkspaceActive && (
          <button
            type="button"
            className="button primary small-button"
            onClick={() => void persist(workspace)}
            disabled={loading || !loaded || saveStatus === "saving" || saveStatus === "saved" || restoringVersion !== null}
          >
            <Save size={14} /> Save now
          </button>
          )}
        </div>
      </header>
      {workspaceError && <p className="inline-error latex-error" role="alert">{workspaceError}</p>}
      {compileError && (
        <div className="inline-error latex-error latex-diagnostic" role="alert">
          <pre>{compileError}</pre>
          {compileLocation && (
            <button type="button" className="button secondary small-button" onClick={openCompileLocation}>
              Open {compileLocation.filename} line {compileLocation.line}
            </button>
          )}
        </div>
      )}
      {!canEdit && <p className="latex-preview-note">You can read and compile this draft but cannot change shared project content.</p>}
      {workspaceError.includes("changed in another session") && (
        <button type="button" className="button secondary small-button latex-reload" onClick={() => void reloadWorkspace()}>
          Reload latest version
        </button>
      )}
      <div className="writing-workspace-tabs" role="group" aria-label="Main document">
        <button
          type="button"
          className={!pythonWorkspaceActive ? "active" : ""}
          aria-pressed={!pythonWorkspaceActive}
          onClick={() => setPythonWorkspaceActive(false)}
        >
          <FileCode2 size={14} /> LaTeX
        </button>
      </div>
      {loading ? (
        <div className="latex-loading"><LoaderCircle className="spin" size={18} /> Loading project files…</div>
      ) : (
        <div className="latex-layout">
          <aside className="latex-sources">
            <div className="latex-files">
              <span className="latex-label">PROJECT FILES</span>
              <button type="button" className={`latex-file ${activeFile === "main.tex" && !pythonWorkspaceActive ? "active" : ""}`} onClick={() => { setHistoryOpen(false); setComparison(null); setPythonWorkspaceActive(false); setActiveFile("main.tex"); }}>
                <FileCode2 size={15} /> main.tex
              </button>
              <button type="button" className={`latex-file ${activeFile === "references.bib" && !pythonWorkspaceActive ? "active" : ""}`} onClick={() => { setHistoryOpen(false); setComparison(null); setPythonWorkspaceActive(false); setActiveFile("references.bib"); }}>
                <BookOpen size={15} /> references.bib
              </button>
            </div>
            <div className="latex-source-group">
              <button
                type="button"
                className={`latex-group-heading python-source-heading${pythonWorkspaceActive ? " active" : ""}`}
                onClick={() => openPythonWorkspace()}
                aria-pressed={pythonWorkspaceActive}
              >
                <Code2 size={14} />
                <span>PYTHON ANALYSIS</span>
                <small>{pythonWorkspaceVisited ? pythonFiles.length : "Open"}</small>
              </button>
              {pythonFiles.map((filename) => (
                <button
                  type="button"
                  className={`latex-file python-source-file${pythonWorkspaceActive && selectedPythonFile === filename ? " active" : ""}`}
                  key={filename}
                  aria-pressed={pythonWorkspaceActive && selectedPythonFile === filename}
                  onClick={() => openPythonWorkspace(filename)}
                >
                  <FileCode2 size={14} /> {filename}
                </button>
              ))}
              {!pythonWorkspaceVisited && (
                <p className="latex-empty">Open Python analysis to manage scripts and generated figures.</p>
              )}
            </div>
            <div className="latex-source-group">
              <div className="latex-group-heading"><Library size={14} /><span>SAVED LITERATURE</span><small>{papers.length}</small></div>
              {papers.length > 0 && (
                <input
                  type="search"
                  className="latex-citation-search"
                  aria-label="Search saved literature to cite"
                  placeholder="Search title, author, year, DOI…"
                  value={citationSearch}
                  onChange={(event) => setCitationSearch(event.target.value)}
                />
              )}
              {papers.length ? citationPapers.length ? citationPapers.map((paper) => (
                <article className="latex-source-card" key={paper.paper_id}>
                  <strong>{paper.title}</strong>
                  <span>{paper.authors[0]?.author_name ?? "Unknown author"} · {paper.publication_year ?? "n.d."}</span>
                  <div className="latex-source-actions">
                    <button type="button" onClick={() => citePaper(paper)} title={`Add ${citationKey(paper)} to references.bib and cite it`} disabled={!canEdit || restoringVersion !== null}>
                      <Code2 size={12} /> Cite
                    </button>
                    {paper.abstract && (
                      <button type="button" onClick={() => citePaper(paper, true)} title="Insert the abstract with its citation" disabled={!canEdit || restoringVersion !== null}>
                        <Upload size={12} /> Abstract
                      </button>
                    )}
                  </div>
                </article>
              )) : <p className="latex-empty">No saved papers match that search.</p> : <p className="latex-empty">Save papers in Literature to cite them here.</p>}
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
                        {canEdit ? "Load editable excerpt" : "Load excerpt"}
                      </button>
                    ) : (
                      <>
                        <textarea
                          aria-label={`Excerpt from ${document.filename}`}
                          value={excerpts[document.document_id]}
                          maxLength={4000}
                          rows={5}
                          readOnly={!canEdit || restoringVersion !== null}
                          onChange={(event) => setExcerpts((current) => ({
                            ...current,
                            [document.document_id]: event.target.value,
                          }))}
                        />
                        <button type="button" className="latex-insert-excerpt" onClick={() => insertDocumentExcerpt(document)} disabled={!canEdit || restoringVersion !== null}>
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
            <div className="latex-editor-content" hidden={pythonWorkspaceActive}>
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
                  <button type="button" className={paneMode === "pdf" ? "active" : ""} onClick={() => setPaneMode("pdf")} aria-pressed={paneMode === "pdf"} title="Compiled PDF">
                    <FileOutput size={14} /><span>PDF</span>
                  </button>
                </div>
              </div>
              {historyOpen && (
                <section className="workspace-history" aria-label={`${activeFile} version history`}>
                  <div className="workspace-history-heading">
                    <strong>{activeFile} history</strong>
                    <button
                      type="button"
                      className="button secondary small-button"
                      onClick={() => void loadHistory(activeFile)}
                      disabled={historyLoading}
                    >
                      {historyLoading ? "Refreshing…" : "Refresh"}
                    </button>
                  </div>
                  <p>Up to 20 changed versions are kept per file. Restoring a version creates a new revision.</p>
                  {historyError && <p className="inline-error" role="alert">{historyError}</p>}
                  {comparisonError && <p className="inline-error" role="alert">{comparisonError}</p>}
                  {historyLoading ? (
                    <p className="latex-empty">Loading history…</p>
                  ) : historyVersions.length ? historyVersions.map((version) => (
                    <div className="workspace-history-item" key={version.version_id}>
                      <span>
                        <strong>Version {version.version_number}</strong>
                        <small>{new Date(version.created_at).toLocaleString()} · {version.author_name ?? "Earlier version"}</small>
                      </span>
                      <button
                        type="button"
                        className="button secondary small-button"
                        onClick={() => void compareVersion(version)}
                        disabled={comparisonLoading !== null || restoringVersion !== null}
                      >
                        {comparisonLoading === version.version_id ? "Loading…" : "Compare"}
                      </button>
                      <button
                        type="button"
                        className="button secondary small-button"
                        onClick={() => void restoreVersion(version)}
                        disabled={!canEdit || restoringVersion !== null}
                      >
                        {restoringVersion === version.version_id ? "Restoring…" : "Restore"}
                      </button>
                    </div>
                  )) : <p className="latex-empty">No saved versions for this file yet.</p>}
                </section>
              )}
              {comparison && comparison.filename === activeFile && (
                <WorkspaceVersionComparison
                  filename={comparison.filename}
                  versionNumber={comparison.version_number}
                  createdAt={comparison.created_at}
                  previousContent={comparison.content}
                  currentContent={
                    comparison.filename === "main.tex"
                      ? workspace.main_tex
                      : workspace.references_bib
                  }
                  onClose={() => setComparison(null)}
                />
              )}
              <div className="latex-citation-tools">
                <label htmlFor="latex-citation-style">Bibliography style</label>
                <select
                  id="latex-citation-style"
                  disabled={!canEdit}
                  onChange={(event) => {
                    if (event.target.value === CUSTOM_CITATION_STYLE) {
                      setCustomCitationStyleSelected(true);
                      setCustomCitationStyleDraft(activeCitationStyle && !isBuiltInCitationStyle ? activeCitationStyle : "");
                      setCitationStyleError("");
                    } else {
                      setCustomCitationStyleSelected(false);
                      changeCitationStyle(event.target.value);
                    }
                  }}
                  value={citationStyle}
                >
                  {CITATION_STYLES.map((style) => <option value={style.value} key={style.value}>{style.label}</option>)}
                  <option value={CUSTOM_CITATION_STYLE}>Custom installed style…</option>
                </select>
                {citationStyle === CUSTOM_CITATION_STYLE && (
                  <>
                    <label htmlFor="latex-custom-citation-style">Custom .bst name</label>
                    <input
                      id="latex-custom-citation-style"
                      className="latex-custom-style-input"
                      aria-describedby="latex-custom-style-help"
                      value={customCitationStyleDraft}
                      placeholder="e.g. ieee-like"
                      disabled={!canEdit || restoringVersion !== null}
                      onChange={(event) => {
                        setCustomCitationStyleDraft(event.target.value);
                        setCitationStyleError("");
                      }}
                    />
                    <button
                      type="button"
                      className="latex-apply-style"
                      onClick={applyCustomCitationStyle}
                      disabled={!canEdit || restoringVersion !== null || !customCitationStyleDraft.trim()}
                    >
                      Apply
                    </button>
                    <small id="latex-custom-style-help">Use an installed style name without .bst.</small>
                  </>
                )}
                {citationStyleError && <span className="latex-citation-warning" role="alert">{citationStyleError}</span>}
                {!!citationIssues.missingKeys.length && (
                  <span className="latex-citation-warning" role="status">
                    Missing BibTeX entries: {citationIssues.missingKeys.join(", ")}
                  </span>
                )}
                {!!citationIssues.duplicateKeys.length && (
                  <span className="latex-citation-warning" role="status">
                    Duplicate BibTeX keys: {citationIssues.duplicateKeys.join(", ")}
                  </span>
                )}
              </div>
              <div className={`latex-panes mode-${paneMode}`}>
                {paneMode !== "preview" && paneMode !== "pdf" && (
                  <div className="latex-source-pane">
                    <div className="latex-editor-caption"><Code2 size={13} /> LaTeX source</div>
                    <textarea
                      ref={editorRef}
                      aria-label={`${activeFile} source`}
                      autoCapitalize="off"
                      autoComplete="off"
                      autoCorrect="off"
                      spellCheck={false}
                      readOnly={!canEdit || restoringVersion !== null}
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
                {paneMode !== "source" && paneMode !== "pdf" && (
                  <div className="latex-preview-pane">
                    <div className="latex-editor-caption"><Eye size={13} /> {activeFile === "main.tex" ? "Quick article preview" : "Bibliography source"}</div>
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
                    <p className="latex-preview-note">Quick structural preview only. Use Compile PDF for full TeX output.</p>
                  </div>
                )}
                {paneMode === "pdf" && (
                  <div className="latex-preview-pane latex-pdf-pane">
                    <div className="latex-editor-caption"><FileOutput size={13} /> Compiled PDF</div>
                    {pdfUrl
                      ? <iframe className="latex-pdf-frame" src={pdfUrl} title="Compiled research draft PDF" />
                      : <p className="latex-empty">Compile the saved draft to view its PDF here.</p>}
                  </div>
                )}
              </div>
            </div>
            {pythonWorkspaceVisited && (
              <div className="latex-python-panel" hidden={!pythonWorkspaceActive}>
                <Suspense fallback={<div className="latex-loading">Loading Python editor…</div>}>
                  <PythonAnalysisWorkspace
                    key={project.project_id}
                    projectId={project.project_id}
                    canEdit={canEdit}
                    request={request}
                    selectedFilename={selectedPythonFile}
                    onExit={() => setPythonWorkspaceActive(false)}
                    onFilesChange={setPythonFiles}
                    onSelectedFileChange={setSelectedPythonFile}
                    onInsertOutput={insertPythonOutput}
                  />
                </Suspense>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
