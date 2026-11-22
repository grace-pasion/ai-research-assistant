import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  Download,
  FileText,
  FileCode2,
  FolderPlus,
  Library,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  Plus,
  Pencil,
  Search,
  Send,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Fragment, type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadFile, fetchPdfObjectUrl, getToken, jsonBody, setToken } from "./api";
import { LatexWorkspace } from "./LatexWorkspace";
import type {
  Annotation,
  BulkDocumentUploadResponse,
  Conversation,
  DocumentRecord,
  DocumentSearchResult,
  Draft,
  PaperImportResponse,
  Paper,
  Project,
  SearchResult,
  Source,
  User,
} from "./types";

type View = "documents" | "papers" | "latex" | "assistant";
type LoginResponse = { access_token: string; user: User };
const MAX_BULK_UPLOAD_COUNT = 20;
type UploadQueueItem = {
  key: string;
  projectId: string;
  file: File;
  filename: string;
  status: string;
  documentId: string | null;
  error: string | null;
};

function App() {
  const [token, setAuthToken] = useState<string | null>(getToken());
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<View>("documents");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [bulkUploads, setBulkUploads] = useState<UploadQueueItem[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [annotationDocumentId, setAnnotationDocumentId] = useState<string | null>(null);
  const [citationPage, setCitationPage] = useState<number | null>(null);
  const [citationExcerpt, setCitationExcerpt] = useState<string | null>(null);
  const [annotationPaperId, setAnnotationPaperId] = useState<string | null>(null);
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentMatches, setDocumentMatches] = useState<DocumentSearchResult[] | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [showNewProject, setShowNewProject] = useState(false);
  const [showEditProject, setShowEditProject] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [provider, setProvider] = useState("openalex");
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [question, setQuestion] = useState("");
  const [askMode, setAskMode] = useState<"question" | "compare" | "directions">("question");

  const request = useCallback(
    async <T,>(path: string, options?: RequestInit) => api<T>(path, options, token),
    [token],
  );

  const loadProjectData = useCallback(
    async (selected: Project) => {
      const id = selected.project_id;
      const [docs, savedPapers, chats] = await Promise.all([
        request<DocumentRecord[]>(`/api/projects/${id}/documents`),
        request<Paper[]>(`/api/projects/${id}/papers`),
        request<Conversation[]>(`/api/projects/${id}/assistant/conversations`),
      ]);
      setDocuments(docs);
      setPapers(savedPapers);
      setConversations(chats);
    },
    [request],
  );

  useEffect(() => {
    if (!token) return;
    let active = true;
    Promise.all([request<User>("/api/auth/me"), request<Project[]>("/api/projects")])
      .then(([me, loaded]) => {
        if (!active) return;
        setUser(me);
        setProjects(loaded);
        setProject((selected) => {
          if (selected && loaded.some((item) => item.project_id === selected.project_id)) return selected;
          return loaded[0] ?? null;
        });
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setAuthToken(null);
        setToken(null);
        setError(cause instanceof Error ? cause.message : "Could not restore your session.");
      });
    return () => {
      active = false;
    };
  }, [request, token]);

  useEffect(() => {
    if (!project || !token) {
      setDocuments([]);
      setPapers([]);
      setConversations([]);
      return;
    }
    loadProjectData(project).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "Could not load the project.");
    });
  }, [loadProjectData, project, token]);

  const processing = useMemo(
    () => documents.some((document) => document.processing_status === "processing"),
    [documents],
  );
  const screeningCounts = useMemo(() => ({
    unread: papers.filter((paper) => paper.screening_status === "unread").length,
    undecided: papers.filter((paper) => paper.screening_status === "undecided").length,
    include: papers.filter((paper) => paper.screening_status === "include").length,
    exclude: papers.filter((paper) => paper.screening_status === "exclude").length,
  }), [papers]);
  const reviewedPaperCount = screeningCounts.undecided + screeningCounts.include + screeningCounts.exclude;
  const openedDocument = annotationDocumentId
    ? documents.find((document) => document.document_id === annotationDocumentId) ?? null
    : null;

  function openDocumentEvidence(
    documentId: string,
    pageNumber: number | null = null,
    excerpt: string | null = null,
  ) {
    setAnnotationDocumentId(documentId);
    setCitationPage(pageNumber);
    setCitationExcerpt(excerpt);
    setView("documents");
  }

  function openSource(source: Source) {
    if (source.kind === "document" && source.document_id) {
      openDocumentEvidence(source.document_id, source.page_number, source.excerpt);
    } else if (source.paper_url) {
      window.open(source.paper_url, "_blank", "noopener,noreferrer");
    }
  }

  useEffect(() => {
    if (!processing || !project) return;
    const timer = window.setInterval(() => {
      request<DocumentRecord[]>(`/api/projects/${project.project_id}/documents`)
        .then(setDocuments)
        .catch((cause: unknown) =>
          setError(cause instanceof Error ? cause.message : "Could not refresh document status."),
        );
    }, 2500);
    return () => window.clearInterval(timer);
  }, [processing, project, request]);

  useEffect(() => {
    if (!documents.length) return;
    setBulkUploads((current) => {
      let changed = false;
      const updated = current.map((item) => {
        if (!item.documentId) return item;
        const document = documents.find((candidate) => candidate.document_id === item.documentId);
        if (!document || (item.status === document.processing_status
          && item.error === document.processing_error)) return item;
        changed = true;
        return {
          ...item,
          status: document.processing_status,
          error: document.processing_error,
        };
      });
      return changed ? updated : current;
    });
  }, [documents]);

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const body: Record<string, string> = {
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    };
    if (authMode === "register") body.name = String(form.get("name") ?? "");
    try {
      const result = await api<LoginResponse>(
        `/api/auth/${authMode === "register" ? "register" : "login"}`,
        { method: "POST", body: jsonBody(body) },
        null,
      );
      setToken(result.access_token);
      setAuthToken(result.access_token);
      setUser(result.user);
      const loaded = await api<Project[]>("/api/projects", {}, result.access_token);
      setProjects(loaded);
      setProject(loaded[0] ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setBusy(true);
    setError("");
    const form = new FormData(formElement);
    try {
      const created = await request<Project>("/api/projects", {
        method: "POST",
        body: jsonBody({
          project_name: form.get("project_name"),
          description: form.get("description"),
        }),
      });
      setProjects((current) => [created, ...current]);
      setProject(created);
      setShowNewProject(false);
      setNotice("Research project created.");
      formElement.reset();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the project.");
    } finally {
      setBusy(false);
    }
  }

  async function updateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setError("");
    try {
      const updated = await request<Project>(`/api/projects/${project.project_id}`, {
        method: "PATCH",
        body: jsonBody({
          project_name: form.get("project_name"),
          description: form.get("description"),
        }),
      });
      setProjects((current) => current.map((item) => item.project_id === updated.project_id ? updated : item));
      setProject(updated);
      setShowEditProject(false);
      setNotice("Project details updated.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update the project.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadDocuments(files: File[]) {
    if (!project || !files.length || uploadingFiles) return;
    if (files.length > MAX_BULK_UPLOAD_COUNT) {
      setError(`Choose no more than ${MAX_BULK_UPLOAD_COUNT} files at once.`);
      return;
    }
    const queued = files.map((file) => ({
      key: crypto.randomUUID(),
      projectId: project.project_id,
      file,
      filename: file.name,
      status: "uploading",
      documentId: null,
      error: null,
    }));
    setBulkUploads((current) => [...current, ...queued].slice(-40));
    setUploadingFiles(true);
    setError("");
    try {
      const form = new FormData();
      files.forEach((file) => form.append("files", file));
      const response = await request<BulkDocumentUploadResponse>(
        `/api/projects/${project.project_id}/documents/bulk`,
        {
          method: "POST",
          body: form,
        },
      );
      const results = queued.map((item, index) => {
        const result = response.results[index];
        return {
          ...item,
          status: result?.document?.processing_status ?? "failed",
          documentId: result?.document?.document_id ?? null,
          error: result?.error ?? result?.document?.processing_error
            ?? (result ? null : "The server did not return an upload result."),
        };
      });
      setBulkUploads((current) => current.map((item) =>
        results.find((result) => result.key === item.key) ?? item));
      const accepted = response.results.filter((result) => result.document).length;
      setNotice(
        `${accepted} of ${files.length} file${files.length === 1 ? "" : "s"} accepted. `
        + "Processing continues on the server after the upload finishes.",
      );
      try {
        await loadProjectData(project);
      } catch (cause) {
        setError(cause instanceof Error
          ? `Files were accepted, but their status could not be refreshed: ${cause.message}`
          : "Files were accepted, but their status could not be refreshed.");
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Upload failed.";
      setBulkUploads((current) => current.map((item) =>
        queued.some((queuedItem) => queuedItem.key === item.key)
          ? { ...item, status: "failed", error: message }
          : item));
    } finally {
      setUploadingFiles(false);
    }
  }

  async function retryBulkUpload(item: UploadQueueItem) {
    if (!project || item.projectId !== project.project_id || uploadingFiles) return;
    setUploadingFiles(true);
    setBulkUploads((current) => current.map((queued) =>
      queued.key === item.key ? { ...queued, status: "uploading", error: null } : queued));
    try {
      let document: DocumentRecord | null = null;
      let uploadError: string | null = null;
      if (item.documentId) {
        document = await request<DocumentRecord>(
          `/api/documents/${item.documentId}/reprocess`,
          { method: "POST" },
        );
      } else {
        const form = new FormData();
        form.append("files", item.file);
        const response = await request<BulkDocumentUploadResponse>(
          `/api/projects/${project.project_id}/documents/bulk`,
          { method: "POST", body: form },
        );
        document = response.results[0]?.document ?? null;
        uploadError = response.results[0]?.error ?? null;
      }
      if (!document) throw new Error(uploadError ?? "The server did not accept this file.");
      setBulkUploads((current) => current.map((queued) =>
        queued.key === item.key
          ? {
            ...queued,
            status: document?.processing_status ?? "processing",
            documentId: document?.document_id ?? null,
            error: document?.processing_error ?? null,
          }
          : queued));
      try {
        await loadProjectData(project);
      } catch (cause) {
        setError(cause instanceof Error
          ? `Retry was accepted, but status could not be refreshed: ${cause.message}`
          : "Retry was accepted, but status could not be refreshed.");
      }
    } catch (cause) {
      setBulkUploads((current) => current.map((queued) =>
        queued.key === item.key
          ? {
            ...queued,
            status: "failed",
            error: cause instanceof Error ? cause.message : "Retry failed.",
          }
          : queued));
    } finally {
      setUploadingFiles(false);
    }
  }

  async function deleteDocument(documentId: string) {
    if (!project || !window.confirm("Delete this document and its extracted text?")) return;
    setBusy(true);
    setError("");
    try {
      await request<void>(`/api/documents/${documentId}`, { method: "DELETE" });
      await loadProjectData(project);
      setNotice("Document deleted.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the document.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocument(document: DocumentRecord) {
    setError("");
    try {
      await downloadFile(`/api/documents/${document.document_id}/download`, document.filename);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not download the document.");
    }
  }

  async function searchDocuments(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || documentQuery.trim().length < 2) return;
    setError("");
    try {
      const results = await request<DocumentSearchResult[]>(
        `/api/projects/${project.project_id}/documents/search?q=${encodeURIComponent(documentQuery.trim())}`,
      );
      setDocumentMatches(results);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Document search failed.");
    }
  }

  async function reprocess(documentId: string) {
    setError("");
    try {
      await request<DocumentRecord>(`/api/documents/${documentId}/reprocess`, { method: "POST" });
      if (project) await loadProjectData(project);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reprocess this document.");
    }
  }

  async function searchPapers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || searchText.trim().length < 2) return;
    setBusy(true);
    setError("");
    try {
      const result = await request<SearchResult>(
        `/api/projects/${project.project_id}/papers/search?q=${encodeURIComponent(searchText)}&provider=${provider}&limit=10`,
      );
      setSearchResults(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Academic search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function importReferences(file: File) {
    if (!project || referenceBusy) return;
    setReferenceBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await request<PaperImportResponse>(
        `/api/projects/${project.project_id}/papers/import`,
        { method: "POST", body: form },
      );
      setNotice(
        `Added ${result.added_count} reference${result.added_count === 1 ? "" : "s"}; `
        + `skipped ${result.duplicate_count} DOI duplicate${result.duplicate_count === 1 ? "" : "s"}.`,
      );
      try {
        await loadProjectData(project);
      } catch (cause) {
        setError(cause instanceof Error
          ? `References were imported, but the project list could not be refreshed: ${cause.message}`
          : "References were imported, but the project list could not be refreshed.");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not import references.");
    } finally {
      setReferenceBusy(false);
    }
  }

  async function exportReferences(format: "ris" | "bibtex") {
    if (!project || !papers.length || referenceBusy) return;
    setReferenceBusy(true);
    setError("");
    try {
      await downloadFile(
        `/api/projects/${project.project_id}/papers/export?format=${format}`,
        format === "ris" ? "references.ris" : "references.bib",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not export references.");
    } finally {
      setReferenceBusy(false);
    }
  }

  async function savePaper(paper: Paper) {
    if (!project) return;
    setError("");
    try {
      await request<void>(`/api/projects/${project.project_id}/papers/${paper.paper_id}/save`, {
        method: "POST",
      });
      await loadProjectData(project);
      setSearchResults((current) =>
        current
          ? {
              ...current,
              results: current.results.map((result) =>
                result.paper_id === paper.paper_id ? { ...result, saved: true } : result,
              ),
            }
          : current,
      );
      setNotice("Paper saved to this project.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this paper.");
    }
  }

  async function unsavePaper(paper: Paper) {
    if (!project) return;
    setError("");
    try {
      await request<void>(`/api/projects/${project.project_id}/papers/${paper.paper_id}/save`, {
        method: "DELETE",
      });
      await loadProjectData(project);
      setNotice("Paper removed from this project.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove this paper.");
    }
  }

  async function importPaperFullText(paper: Paper) {
    if (!project) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const document = await request<DocumentRecord>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/full-text`,
        { method: "POST" },
      );
      await loadProjectData(project);
      openDocumentEvidence(document.document_id);
      if (document.processing_status === "needs_api_key") {
        setNotice("Full text was extracted. Add an OpenAI API key to make it available to AI queries.");
      } else if (document.processing_status === "ready") {
        setNotice("Full text is ready to read and query.");
      } else {
        setNotice("Open-access PDF added. Text extraction is running; it will be available to query when processing finishes.");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not import the paper's full text.");
    } finally {
      setBusy(false);
    }
  }

  async function updatePaperScreening(
    paper: Paper,
    screeningStatus: Paper["screening_status"],
    screeningNote: string,
  ) {
    if (!project) return;
    setError("");
    try {
      const updated = await request<Pick<Paper, "screening_status" | "screening_note">>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/screening`,
        {
          method: "PATCH",
          body: jsonBody({ screening_status: screeningStatus, screening_note: screeningNote }),
        },
      );
      setPapers((current) => current.map((item) =>
        item.paper_id === paper.paper_id ? { ...item, ...updated } : item,
      ));
      setNotice("Screening decision saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this screening decision.");
    }
  }

  async function openConversation(item: Conversation) {
    if (!project) return;
    setError("");
    try {
      const loaded = await request<Conversation>(
        `/api/projects/${project.project_id}/assistant/conversations/${item.conversation_id}`,
      );
      setConversation(loaded);
      setDraft(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not open this conversation.");
    }
  }

  async function askQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || question.trim().length < 3) return;
    setBusy(true);
    setError("");
    setNotice("");
    setDraft(null);
    try {
      const generated = await request<Draft>(`/api/projects/${project.project_id}/assistant/draft`, {
        method: "POST",
        body: jsonBody({
          question: question.trim(),
          mode: askMode,
          conversation_id: conversation?.conversation_id ?? null,
        }),
      });
      setDraft(generated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate an answer.");
    } finally {
      setBusy(false);
    }
  }

  async function approveDraft() {
    if (!project || !draft) return;
    setBusy(true);
    setError("");
    try {
      const saved = await request<Conversation>(
        `/api/projects/${project.project_id}/assistant/approve`,
        { method: "POST", body: jsonBody({ approval_token: draft.approval_token }) },
      );
      setConversation(saved);
      setDraft(null);
      setQuestion("");
      await loadProjectData(project);
      setNotice("Answer and conversation saved after your approval.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not approve this answer.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteProject() {
    if (!project || !window.confirm(`Delete “${project.project_name}” and all its data?`)) return;
    setBusy(true);
    setError("");
    try {
      await request<void>(`/api/projects/${project.project_id}`, { method: "DELETE" });
      const remaining = projects.filter((item) => item.project_id !== project.project_id);
      setProjects(remaining);
      setProject(remaining[0] ?? null);
      setConversation(null);
      setDraft(null);
      setNotice("Project deleted.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the project.");
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    setToken(null);
    setAuthToken(null);
    setUser(null);
    setProjects([]);
    setProject(null);
    setConversation(null);
    setDraft(null);
    setError("");
  }

  if (!token || !user) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="brand-mark"><BookOpen size={22} /></div>
          <p className="eyebrow">YOUR RESEARCH, IN ONE PLACE</p>
          <h1>{authMode === "login" ? "Welcome back." : "Start a research space."}</h1>
          <p className="muted">
            Organize documents, discover literature, and ask questions grounded in your sources.
          </p>
          {error && <Notice kind="error" text={error} />}
          <form onSubmit={handleAuth} className="stack-form">
            {authMode === "register" && (
              <label>
                Name
                <input name="name" autoComplete="name" required maxLength={120} />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" autoComplete="email" required />
            </label>
            <label>
              Password <span className="field-note">{authMode === "register" && "12+ characters; avoid common passwords"}</span>
              <input
                name="password"
                type="password"
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                minLength={authMode === "register" ? 12 : 1}
                required
              />
            </label>
            <button className="button primary wide" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : null}
              {authMode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
          <button
            className="text-button centered"
            onClick={() => {
              setAuthMode(authMode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {authMode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
          </button>
          <a className="text-button centered" href={`${window.location.pathname}?portal=admin`}>
            Administrator sign in
          </a>
          <p className="tiny-note">Your research workspace is private to your account.</p>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" aria-label="Fieldnotes home">
          <span className="brand-mark"><BookOpen size={19} /></span>
          <span>fieldnotes<span className="brand-dot">.</span></span>
        </a>
        <div className="sidebar-label">WORKSPACE</div>
        <button className="new-project-button" onClick={() => setShowNewProject(true)}>
          <FolderPlus size={16} /> New project <Plus size={15} className="push-right" />
        </button>
        <nav className="project-list" aria-label="Research projects">
          {projects.map((item) => (
            <button
              className={`project-link ${project?.project_id === item.project_id ? "selected" : ""}`}
              key={item.project_id}
              onClick={() => {
                setProject(item);
                setConversation(null);
                setDraft(null);
                setView("documents");
                setNotice("");
              }}
            >
              <span className="project-bullet" />
              <span className="project-link-name">{item.project_name}</span>
            </button>
          ))}
          {!projects.length && <p className="sidebar-empty">Create your first research project.</p>}
        </nav>
        <div className="sidebar-spacer" />
        <div className="account-card">
          <span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span>
          <span className="account-name">{user.name}</span>
          <button className="icon-button logout" title="Sign out" onClick={signOut}>
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span><span className="crumb-separator">/</span>
            <span className="crumb-current">{project?.project_name ?? "No project selected"}</span>
          </div>
          <div className="topbar-right">
            <span className="private-badge"><ShieldCheck size={14} /> Private workspace</span>
            {project && (
              <button className="icon-button danger-hover" title="Delete project" onClick={deleteProject}>
                <Trash2 size={16} />
              </button>
            )}
          </div>
        </header>

        <div className="content-area">
          {error && <Notice kind="error" text={error} onClose={() => setError("")} />}
          {notice && <Notice kind="success" text={notice} onClose={() => setNotice("")} />}
          {showNewProject && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget) setShowNewProject(false);
            }}>
              <form className="modal-card stack-form" onSubmit={createProject}>
                <div className="modal-heading">
                  <div><p className="eyebrow">WORKSPACE</p><h2>New research project</h2></div>
                  <button type="button" className="icon-button" onClick={() => setShowNewProject(false)} aria-label="Close">
                    <X size={18} />
                  </button>
                </div>
                <label>Project name<input name="project_name" required maxLength={160} autoFocus /></label>
                <label>Description<textarea name="description" rows={3} maxLength={5000} /></label>
                <button className="button primary" disabled={busy}>Create project</button>
              </form>
            </div>
          )}
          {showEditProject && project && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget) setShowEditProject(false);
            }}>
              <form className="modal-card stack-form" onSubmit={(event) => void updateProject(event)}>
                <div className="modal-heading">
                  <div><p className="eyebrow">WORKSPACE</p><h2>Edit project details</h2></div>
                  <button type="button" className="icon-button" onClick={() => setShowEditProject(false)} aria-label="Close">
                    <X size={18} />
                  </button>
                </div>
                <label>Project name<input name="project_name" required maxLength={160} defaultValue={project.project_name} autoFocus /></label>
                <label>Description<textarea name="description" rows={3} maxLength={5000} defaultValue={project.description} /></label>
                <button className="button primary" disabled={busy}>Save changes</button>
              </form>
            </div>
          )}

          {!project ? (
            <section className="empty-workspace">
              <div className="empty-icon"><FolderPlus size={24} /></div>
              <p className="eyebrow">A FRESH START</p>
              <h1>Make a home for your research.</h1>
              <p className="muted">Create a project to collect documents, papers, and source-backed conversations.</p>
              <button className="button primary" onClick={() => setShowNewProject(true)}>
                <Plus size={17} /> Create a project
              </button>
            </section>
          ) : (
            <>
              <section className="project-heading">
                <div>
                  <p className="eyebrow">RESEARCH PROJECT</p>
                  <h1>{project.project_name}</h1>
                  <p className="project-description">{project.description || "A focused space for your research."}</p>
                </div>
                <div className="project-stat">
                  <span>{documents.length}</span><small>documents</small>
                  <i />
                  <span>{papers.length}</span><small>saved papers</small>
                </div>
                <button className="button secondary small-button edit-project" onClick={() => setShowEditProject(true)}>
                  <Pencil size={14} /> Edit
                </button>
              </section>

              <div className="tab-bar" role="tablist" aria-label="Project sections">
                <TabButton active={view === "documents"} onClick={() => setView("documents")} icon={<FileText size={16} />}>Documents</TabButton>
                <TabButton active={view === "papers"} onClick={() => setView("papers")} icon={<Library size={16} />}>Literature</TabButton>
                <TabButton active={view === "latex"} onClick={() => setView("latex")} icon={<FileCode2 size={16} />}>Main document</TabButton>
                <TabButton active={view === "assistant"} onClick={() => setView("assistant")} icon={<MessageSquareText size={16} />}>Ask & explore</TabButton>
              </div>

              <div className={view === "latex" ? "" : "latex-workspace-hidden"} aria-hidden={view !== "latex"}>
                <LatexWorkspace
                  key={project.project_id}
                  project={project}
                  documents={documents}
                  papers={papers}
                  request={request}
                />
              </div>

              {view === "documents" && (
                <section className="section-content">
                  {openedDocument ? (
                    <div className="document-reader-page">
                      <div className="document-reader-header">
                        <button className="button secondary small-button" onClick={() => setAnnotationDocumentId(null)}>
                          <ArrowLeft size={14} /> Back to documents
                        </button>
                        <div className="document-reader-title">
                          <h2>{openedDocument.filename}</h2>
                          <p>{formatBytes(openedDocument.file_size)} · Added {new Date(openedDocument.uploaded_at).toLocaleDateString()}</p>
                        </div>
                        <StatusPill status={openedDocument.processing_status} />
                        <button className="icon-button" title="Download original" onClick={() => void downloadDocument(openedDocument)}>
                          <Download size={16} />
                        </button>
                      </div>
                      {openedDocument.processing_error && <p className="inline-error">{openedDocument.processing_error}</p>}
                      {citationExcerpt && (
                        <aside className="citation-evidence">
                          <strong>{citationPage ? `Cited passage · PDF page ${citationPage}` : "Cited passage"}</strong>
                          <p>{citationExcerpt}</p>
                        </aside>
                      )}
                      {openedDocument.file_type === "pdf" && (
                        <DocumentPdfPreview
                          documentId={openedDocument.document_id}
                          pageNumber={citationPage}
                        />
                      )}
                      <AnnotationEditor
                        key={openedDocument.document_id}
                        annotationsPath={`/api/projects/${project.project_id}/documents/${openedDocument.document_id}/annotations`}
                        sourcePath={`/api/documents/${openedDocument.document_id}/reader`}
                        sourceStatus={openedDocument.processing_status}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="section-heading">
                        <div><h2>Research documents</h2><p>Upload up to 20 files at once. Keep this window open until they are accepted; processing can then continue after you close it.</p></div>
                        <div className="upload-control">
                          <label className="button primary upload-button">
                            <Upload size={16} /> {uploadingFiles ? "Uploading…" : "Add documents"}
                            <input name="files" type="file" accept=".pdf,.docx,.txt,.md" multiple disabled={uploadingFiles} onChange={(event) => {
                              const files = Array.from(event.currentTarget.files ?? []);
                              if (files.length) void uploadDocuments(files);
                              event.currentTarget.value = "";
                            }} />
                          </label>
                        </div>
                      </div>
                      {bulkUploads.some((item) => item.projectId === project.project_id) && (
                        <section className="bulk-upload-status" aria-live="polite">
                          <div className="bulk-upload-heading">
                            <strong>Recent uploads</strong>
                            <span>Processing runs on the server after each file is accepted.</span>
                          </div>
                          {bulkUploads.filter((item) => item.projectId === project.project_id).map((item) => (
                            <div className="bulk-upload-item" key={item.key}>
                              <div className="bulk-upload-file">
                                <strong>{item.filename}</strong>
                                {item.error && <small>{item.error}</small>}
                              </div>
                              <StatusPill status={item.status} />
                              {item.status === "failed" && (
                                <button
                                  className="button secondary small-button"
                                  disabled={uploadingFiles}
                                  onClick={() => void retryBulkUpload(item)}
                                >
                                  Retry
                                </button>
                              )}
                            </div>
                          ))}
                        </section>
                      )}
                      {!!documents.length && (
                        <form className="document-search" onSubmit={(event) => void searchDocuments(event)}>
                          <Search size={16} />
                          <input value={documentQuery} onChange={(event) => setDocumentQuery(event.target.value)} placeholder="Find text within your documents…" minLength={2} maxLength={200} />
                          <button className="button secondary small-button" disabled={documentQuery.trim().length < 2}>Search documents</button>
                        </form>
                      )}
                      {documentMatches && (
                        <div className="document-search-results">
                          <div className="result-label"><span>Matches for “{documentQuery}”</span><button className="text-button" onClick={() => setDocumentMatches(null)} type="button">Clear</button></div>
                          {documentMatches.length ? documentMatches.map((match) => (
                            <article className="document-match" key={match.document.document_id}>
                              <button
                                className="document-open-link"
                                type="button"
                                onClick={() => openDocumentEvidence(match.document.document_id)}
                              >
                                {match.document.filename}
                              </button>
                              <p>{match.excerpt}</p>
                            </article>
                          )) : <p className="muted compact">No extracted text matched that search.</p>}
                        </div>
                      )}
                      {!documents.length ? (
                        <EmptyState icon={<FileText size={22} />} title="No documents yet" text="Add a PDF, Word document, plain text, or Markdown file to begin." />
                      ) : (
                        <div className="document-list">
                          {documents.map((document) => (
                            <article className="document-row" key={document.document_id}>
                              <div className="file-icon"><FileText size={18} /></div>
                              <div className="document-info">
                                <button
                                  className="document-open-link"
                                  type="button"
                                  onClick={() => openDocumentEvidence(document.document_id)}
                                >
                                  {document.filename}
                                </button>
                                <span>{formatBytes(document.file_size)} · {new Date(document.uploaded_at).toLocaleDateString()}</span>
                                {document.processing_error && <small className="inline-error">{document.processing_error}</small>}
                              </div>
                              <StatusPill status={document.processing_status} />
                              <button className="icon-button" title="Download original" onClick={() => void downloadDocument(document)}>
                                <Download size={16} />
                              </button>
                              {document.processing_status !== "processing" && document.processing_status !== "ready" && (
                                <button className="button secondary small-button" onClick={() => void reprocess(document.document_id)}>
                                  {document.processing_status === "failed" ? "Retry" : "Reprocess"}
                                </button>
                              )}
                              <button className="icon-button danger-hover" title="Delete document" onClick={() => void deleteDocument(document.document_id)}>
                                <Trash2 size={16} />
                              </button>
                            </article>
                          ))}
                        </div>
                      )}
                      {processing && <p className="processing-note"><LoaderCircle className="spin" size={15} /> Extracting text and preparing documents…</p>}
                    </>
                  )}
                </section>
              )}

              {view === "papers" && (
                <section className="section-content">
                  <div className="section-heading">
                    <div><h2>Discover literature</h2><p>Search scholarly indexes by topic or meaning; abstracts are semantically ranked when OpenAI is configured.</p></div>
                  </div>
                  <div className="reference-toolbar">
                    <div className="reference-toolbar-copy">
                      <strong>Reference import/export</strong>
                      <span>Import RIS or BibTeX; duplicates with matching DOIs are skipped.</span>
                    </div>
                    <div className="reference-actions">
                      <label className="button secondary small-button reference-import-button">
                        {referenceBusy ? <LoaderCircle className="spin" size={14} /> : <Upload size={14} />}
                        Import file
                        <input
                          type="file"
                          accept=".ris,.bib,.bibtex"
                          aria-label="Import RIS or BibTeX bibliography"
                          disabled={referenceBusy}
                          onChange={(event) => {
                            const file = event.currentTarget.files?.[0];
                            if (file) void importReferences(file);
                            event.currentTarget.value = "";
                          }}
                        />
                      </label>
                      <button
                        className="button secondary small-button"
                        disabled={referenceBusy || !papers.length}
                        onClick={() => void exportReferences("ris")}
                      >
                        <Download size={14} /> Export RIS
                      </button>
                      <button
                        className="button secondary small-button"
                        disabled={referenceBusy || !papers.length}
                        onClick={() => void exportReferences("bibtex")}
                      >
                        <Download size={14} /> Export BibTeX
                      </button>
                    </div>
                  </div>
                  <form className="search-form" onSubmit={(event) => void searchPapers(event)}>
                    <Search size={18} />
                    <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search a topic, title, author, or DOI…" minLength={2} />
                    <select value={provider} onChange={(event) => setProvider(event.target.value)} aria-label="Academic search provider">
                      <option value="openalex">OpenAlex</option>
                      <option value="crossref">Crossref</option>
                    </select>
                    <button className="button primary" disabled={busy || searchText.trim().length < 2}>
                      {busy ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />} Search
                    </button>
                  </form>
                  {searchResults && (
                    <div className="result-group">
                      <div className="result-label"><span>Search results</span><small>{searchResults.results.length} papers · {searchResults.provider}</small></div>
                      {searchResults.results.length ? searchResults.results.map((paper) => (
                        <PaperCard key={paper.paper_id} paper={paper} onSave={() => void savePaper(paper)} />
                      )) : <EmptyState icon={<Search size={21} />} title="No results found" text="Try a broader query or use the other search provider." />}
                    </div>
                  )}
                  <div className="result-group saved-group">
                    <div className="result-label"><span>Saved to this project</span><small>{papers.length} papers</small></div>
                    <section className="screening-progress" aria-label="Literature screening progress">
                      <div className="screening-progress-heading">
                        <strong>Screening progress</strong>
                        <span>{reviewedPaperCount} of {papers.length} reviewed</span>
                      </div>
                      <progress
                        max={Math.max(papers.length, 1)}
                        value={reviewedPaperCount}
                        aria-label={`${reviewedPaperCount} of ${papers.length} papers screened`}
                      />
                      <div className="screening-counts">
                        <span>{screeningCounts.unread} unread</span>
                        <span>{screeningCounts.undecided} undecided</span>
                        <span>{screeningCounts.include} included</span>
                        <span>{screeningCounts.exclude} excluded</span>
                      </div>
                    </section>
                    {papers.length ? papers.map((paper) => (
                      <Fragment key={paper.paper_id}>
                        <PaperCard
                          paper={paper}
                          saved
                          onScreeningChange={(status, note) => void updatePaperScreening(paper, status, note)}
                          onRemove={() => void unsavePaper(paper)}
                          onAnnotate={() => setAnnotationPaperId((current) => current === paper.paper_id ? null : paper.paper_id)}
                          onImportFullText={() => void importPaperFullText(paper)}
                          importingFullText={busy}
                        />
                        {annotationPaperId === paper.paper_id && (
                          <AnnotationEditor
                            key={`annotations-${paper.paper_id}`}
                            annotationsPath={`/api/projects/${project.project_id}/papers/${paper.paper_id}/annotations`}
                            sourceText={paper.abstract?.replace(/<[^>]*>/g, "") ?? ""}
                          />
                        )}
                      </Fragment>
                    )) : <p className="muted compact">Your saved papers will appear here.</p>}
                  </div>
                </section>
              )}

              {view === "assistant" && (
                <section className="assistant-layout">
                  <aside className="conversation-sidebar">
                    <div className="conversation-heading">
                      <span>CONVERSATIONS</span>
                      <button className="icon-button" title="New conversation" onClick={() => {
                        setConversation(null);
                        setDraft(null);
                      }}><Plus size={17} /></button>
                    </div>
                    {conversations.map((item) => (
                      <button className={`conversation-link ${conversation?.conversation_id === item.conversation_id ? "active" : ""}`} key={item.conversation_id} onClick={() => void openConversation(item)}>
                        <MessageSquareText size={15} /><span>{item.title}</span>
                      </button>
                    ))}
                    {!conversations.length && <p className="sidebar-empty">Approved conversations appear here.</p>}
                  </aside>
                  <div className="chat-panel">
                    <div className="chat-header">
                      <div><span className="chat-kicker">GROUNDED IN YOUR SOURCES</span><h2>{conversation?.title ?? "Research assistant"}</h2></div>
                      <select value={askMode} onChange={(event) => setAskMode(event.target.value as typeof askMode)} aria-label="Assistant mode">
                        <option value="question">Ask a question</option>
                        <option value="compare">Compare sources</option>
                        <option value="directions">Explore research gaps</option>
                      </select>
                    </div>
                    <div className="chat-messages">
                      {conversation?.messages?.map((message) => (
                        <div className={`message ${message.role}`} key={message.message_id}>
                          <div className="message-label">{message.role === "assistant" ? "FIELDNOTES" : "YOU"}</div>
                          <AnswerContent content={message.content} sources={message.sources} onSourceClick={openSource} />
                          {message.role === "assistant" && (
                            <>
                              {!!message.sources.length && (
                                <div className="source-list saved-sources">
                                  <span className="source-list-label">CITED SOURCES</span>
                                  {message.sources.map((source, index) => (
                                    <article className="source-card" key={`${source.kind}-${source.source_id}`}>
                                      <span className="source-index">S{index + 1}</span>
                                      <div>
                                        <strong>{source.title}</strong>
                                        {source.page_number && <span className="source-page">PDF · page {source.page_number}</span>}
                                        <p>{source.excerpt}</p>
                                        {source.kind === "document" && source.document_id && (
                                          <button className="source-open-button" onClick={() => openSource(source)}>
                                            {source.page_number ? `Open page ${source.page_number}` : "Open document"}
                                          </button>
                                        )}
                                      </div>
                                      {source.kind === "paper" && source.paper_url && (
                                        <a className="source-link" href={source.paper_url} target="_blank" rel="noreferrer" aria-label="Open cited paper"><ArrowUpRight size={15} /></a>
                                      )}
                                    </article>
                                  ))}
                                </div>
                              )}
                              <span className="approved-label"><ShieldCheck size={13} /> Human-reviewed</span>
                            </>
                          )}
                        </div>
                      ))}
                      {draft && (
                        <div className="draft-review">
                          <div className="review-topline"><span className="pending-dot" /> REVIEW REQUIRED <span>Not saved yet</span></div>
                          <AnswerContent content={draft.answer} sources={draft.sources} onSourceClick={openSource} />
                          {!!draft.sources.length && (
                            <div className="source-list">
                              <span className="source-list-label">SOURCES TO REVIEW</span>
                              {draft.sources.map((source, index) => (
                                <article className="source-card" key={`${source.kind}-${source.source_id}`}>
                                  <span className="source-index">S{index + 1}</span>
                                  <div>
                                    <strong>{source.title}</strong>
                                    {source.page_number && <span className="source-page">PDF · page {source.page_number}</span>}
                                    <p>{source.excerpt}</p>
                                    {source.kind === "document" && source.document_id && (
                                      <button className="source-open-button" onClick={() => openSource(source)}>
                                        {source.page_number ? `Open page ${source.page_number}` : "Open document"}
                                      </button>
                                    )}
                                  </div>
                                  {source.kind === "paper" && source.paper_url && (
                                    <a className="source-link" href={source.paper_url} target="_blank" rel="noreferrer" aria-label="Open cited paper"><ArrowUpRight size={15} /></a>
                                  )}
                                </article>
                              ))}
                            </div>
                          )}
                          <div className="review-actions">
                            <button className="button secondary" onClick={() => setDraft(null)} disabled={busy}><X size={16} /> Discard</button>
                            <button className="button approve" onClick={() => void approveDraft()} disabled={busy}>
                              {busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Approve & save
                            </button>
                          </div>
                        </div>
                      )}
                      {!conversation?.messages?.length && !draft && (
                        <div className="chat-empty">
                          <div className="empty-icon"><MessageSquareText size={23} /></div>
                          <h3>Think with your sources.</h3>
                          <p>Ask a question, compare saved papers, or explore a potential research direction. Every generated answer waits for your approval before it is saved.</p>
                          <div className="suggestion-row">
                            <button onClick={() => { setAskMode("question"); setQuestion("What are the main findings across my sources?"); }}>Summarize key findings <ArrowUpRight size={14} /></button>
                            <button onClick={() => { setAskMode("directions"); setQuestion("What research directions could follow from these sources?"); }}>Explore next directions <ArrowUpRight size={14} /></button>
                          </div>
                        </div>
                      )}
                    </div>
                    <form className="composer" onSubmit={(event) => void askQuestion(event)}>
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            event.currentTarget.form?.requestSubmit();
                          }
                        }}
                        placeholder="Ask about your sources, or ask me to find a relevant paper…"
                        rows={2}
                        maxLength={5000}
                        aria-label="Research question"
                      />
                      <div className="composer-bottom">
                        <span><ShieldCheck size={13} /> Answers are drafts until you approve them</span>
                        <button className="button primary send-button" disabled={busy || question.trim().length < 3}>
                          {busy ? <LoaderCircle className="spin" size={16} /> : <Send size={15} />} Generate
                        </button>
                      </div>
                    </form>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
        <footer className="app-footer">
          <span>Built for thoughtful research.</span><span>OpenAlex · Crossref · OpenAI</span>
        </footer>
      </main>
    </div>
  );
}

function AnswerContent({
  content,
  sources,
  onSourceClick,
}: {
  content: string;
  sources: Source[];
  onSourceClick: (source: Source) => void;
}) {
  const matrixRows = parseComparisonMatrix(content);
  if (matrixRows) {
    const headers = [
      "Source",
      "Research question",
      "Methods",
      "Sampling",
      "Findings",
      "Limitations",
      "Citations",
    ];
    return (
      <div className="comparison-matrix-wrap">
        <table className="comparison-matrix">
          <caption>Evidence comparison matrix</caption>
          <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
          <tbody>
            {matrixRows.map((row, rowIndex) => (
              <tr key={`${row[0]}-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>
                    {renderCitedText(cell, sources, onSourceClick)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="message-content">
      {renderCitedText(content, sources, onSourceClick)}
    </div>
  );
}

function parseComparisonMatrix(content: string): string[][] | null {
  const lines = content.split("\n");
  const expectedHeader =
    "| Source | Research question | Methods | Sampling | Findings | Limitations | Citations |";
  if (lines[0] !== expectedHeader) return null;
  const rows = lines.slice(2).map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()));
  return rows.length && rows.every((row) => row.length === 7) ? rows : null;
}

function renderCitedText(
  content: string,
  sources: Source[],
  onSourceClick: (source: Source) => void,
) {
  return content.split(/(\[S\d+\]|\[Missing evidence\])/g).map((part, index) => {
    const citation = /^\[S(\d+)\]$/.exec(part);
    const source = citation ? sources[Number(citation[1]) - 1] : undefined;
    if (source) {
      return (
        <button
          className="citation-ref"
          key={`${part}-${index}`}
          onClick={() => onSourceClick(source)}
          type="button"
          aria-label={`Open cited source ${citation?.[1]}`}
        >
          {part}
        </button>
      );
    }
    if (part === "[Missing evidence]") {
      return <span className="missing-evidence" key={index}>Missing evidence</span>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function DocumentPdfPreview({
  documentId,
  pageNumber,
}: {
  documentId: string;
  pageNumber: number | null;
}) {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setPdfUrl(null);
    setError("");
    fetchPdfObjectUrl(`/api/documents/${documentId}/download`)
      .then((url) => {
        objectUrl = url;
        if (active) setPdfUrl(url);
        else URL.revokeObjectURL(url);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load the original PDF.");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId]);

  return (
    <details className="citation-pdf-preview" open={pageNumber !== null}>
      <summary>{pageNumber ? `Original PDF · page ${pageNumber}` : "View original PDF"}</summary>
      {error && <p className="inline-error">{error}</p>}
      {!error && !pdfUrl && <p className="muted compact">Loading original PDF…</p>}
      {pdfUrl && (
        <iframe
          title="Original research document"
          src={`${pdfUrl}#page=${pageNumber ?? 1}`}
        />
      )}
    </details>
  );
}

function Notice({ kind, text, onClose }: { kind: "error" | "success"; text: string; onClose?: () => void }) {
  return (
    <div className={`notice ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {kind === "error" ? <AlertCircle size={16} /> : <Check size={16} />}
      <span>{text}</span>
      {onClose && <button className="icon-button" onClick={onClose} aria-label="Dismiss"><X size={15} /></button>}
    </div>
  );
}

function TabButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button role="tab" aria-selected={active} className={`tab-button ${active ? "active" : ""}`} onClick={onClick}>
      {icon}{children}<ChevronDown size={13} className="tab-caret" />
    </button>
  );
}

function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{text}</p></div>;
}

function StatusPill({ status }: { status: string }) {
  const labels: Record<string, string> = {
    uploading: "Uploading",
    processing: "Processing",
    ready: "Ready",
    needs_api_key: "Needs API key",
    failed: "Failed",
  };
  return <span className={`status-pill status-${status}`}>{["uploading", "processing"].includes(status) && <LoaderCircle size={12} className="spin" />}{labels[status] ?? status}</span>;
}

function PaperCard({
  paper,
  saved = false,
  onSave,
  onRemove,
  onAnnotate,
  onScreeningChange,
  onImportFullText,
  importingFullText,
}: {
  paper: Paper;
  saved?: boolean;
  onSave?: () => void;
  onRemove?: () => void;
  onAnnotate?: () => void;
  onScreeningChange?: (status: Paper["screening_status"], note: string) => void;
  onImportFullText?: () => void;
  importingFullText?: boolean;
}) {
  const [screeningStatus, setScreeningStatus] = useState(paper.screening_status);
  const [screeningNote, setScreeningNote] = useState(paper.screening_note);

  useEffect(() => {
    setScreeningStatus(paper.screening_status);
    setScreeningNote(paper.screening_note);
  }, [paper.screening_status, paper.screening_note]);

  return (
    <article className="paper-card">
      <div className="paper-icon"><Library size={17} /></div>
      <div className="paper-main">
        <h3>{paper.title}</h3>
        <p className="paper-meta">
          {[paper.authors.slice(0, 4).map((author) => author.author_name).join(", "), paper.publication_year, paper.venue, paper.citation_count != null ? `${paper.citation_count.toLocaleString()} citations` : ""].filter(Boolean).join(" · ") || paper.api_provider}
        </p>
        {paper.abstract && <p className="paper-abstract">{paper.abstract.replace(/<[^>]*>/g, "").slice(0, 500)}{paper.abstract.length > 500 ? "…" : ""}</p>}
        {paper.doi && <p className="doi-line">DOI: {paper.doi.replace(/^https?:\/\/doi\.org\//, "")}</p>}
        {saved && (
          <div className="screening-controls">
            <label>
              Decision
              <select
                value={screeningStatus}
                onChange={(event) => setScreeningStatus(event.target.value as Paper["screening_status"])}
                aria-label={`Screening decision for ${paper.title}`}
              >
                <option value="unread">Unread</option>
                <option value="undecided">Undecided</option>
                <option value="include">Include</option>
                <option value="exclude">Exclude</option>
              </select>
            </label>
            <label>
              Reason / note
              <input
                value={screeningNote}
                onChange={(event) => setScreeningNote(event.target.value)}
                maxLength={500}
                placeholder="Add a short reason (optional)"
                aria-label={`Screening note for ${paper.title}`}
              />
            </label>
            <button
              className="button secondary small-button"
              onClick={() => onScreeningChange?.(screeningStatus, screeningNote)}
              disabled={
                screeningStatus === paper.screening_status &&
                screeningNote === paper.screening_note
              }
            >
              Save decision
            </button>
          </div>
        )}
      </div>
      <div className="paper-actions">
        {paper.paper_url && <a className="icon-button" href={paper.paper_url} target="_blank" rel="noreferrer" title="Open paper"><ArrowUpRight size={16} /></a>}
        {saved ? (
          <>
            <button className="button secondary small-button" onClick={onAnnotate}><Pencil size={13} /> Annotate</button>
            <button className="button secondary small-button" onClick={onImportFullText} disabled={importingFullText}>
              {importingFullText ? <LoaderCircle size={13} className="spin" /> : <FileText size={13} />}
              {importingFullText ? "Importing…" : "Extract full text"}
            </button>
            <button className="button secondary small-button" onClick={onRemove}><X size={14} /> Remove</button>
          </>
        ) : (
          <button className="button secondary small-button" onClick={onSave}><Plus size={15} /> Save</button>
        )}
      </div>
    </article>
  );
}

function AnnotationEditor({
  annotationsPath,
  sourcePath,
  sourceText,
  sourceStatus,
}: {
  annotationsPath: string;
  sourcePath?: string;
  sourceText?: string;
  sourceStatus?: string;
}) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [text, setText] = useState(sourceText ?? "");
  const [note, setNote] = useState("");
  const [selection, setSelection] = useState<{ quote: string; start_offset: number; end_offset: number } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editNote, setEditNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sourceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const annotationRequest = api<Annotation[]>(annotationsPath);
    const textRequest = sourcePath
      ? api<{ text: string }>(sourcePath)
      : Promise.resolve({ text: sourceText ?? "" });
    Promise.all([annotationRequest, textRequest])
      .then(([loadedAnnotations, reader]) => {
        if (!active) return;
        setAnnotations(loadedAnnotations);
        setText(reader.text);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load annotations.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [annotationsPath, sourcePath, sourceStatus, sourceText]);

  function captureSelection() {
    const container = sourceRef.current;
    const selected = window.getSelection();
    if (!container || !selected || selected.isCollapsed || !selected.anchorNode || !selected.focusNode ||
      !container.contains(selected.anchorNode) || !container.contains(selected.focusNode)) {
      setError("Select text in the source first.");
      return;
    }
    const range = selected.getRangeAt(0);
    const preceding = range.cloneRange();
    preceding.selectNodeContents(container);
    preceding.setEnd(range.startContainer, range.startOffset);
    const start = Array.from(preceding.toString()).length;
    const quote = range.toString();
    if (!quote.trim()) {
      setError("Select text in the source first.");
      return;
    }
    setSelection({ quote, start_offset: start, end_offset: start + Array.from(quote).length });
    setError("");
  }

  async function saveAnnotation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = await api<Annotation>(annotationsPath, {
        method: "POST",
        body: jsonBody({
          quote: selection?.quote ?? null,
          note: note.trim(),
          start_offset: selection?.start_offset ?? null,
          end_offset: selection?.end_offset ?? null,
        }),
      });
      setAnnotations((current) => [...current, saved]);
      setNote("");
      setSelection(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this annotation.");
    } finally {
      setBusy(false);
    }
  }

  async function updateAnnotation(annotation: Annotation) {
    setBusy(true);
    setError("");
    try {
      const updated = await api<Annotation>(`${annotationsPath}/${annotation.annotation_id}`, {
        method: "PATCH",
        body: jsonBody({ note: editNote }),
      });
      setAnnotations((current) => current.map((item) => item.annotation_id === updated.annotation_id ? updated : item));
      setEditingId(null);
      setEditNote("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this note.");
    } finally {
      setBusy(false);
    }
  }

  async function deleteAnnotation(annotation: Annotation) {
    setBusy(true);
    setError("");
    try {
      await api<void>(`${annotationsPath}/${annotation.annotation_id}`, { method: "DELETE" });
      setAnnotations((current) => current.filter((item) => item.annotation_id !== annotation.annotation_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this annotation.");
    } finally {
      setBusy(false);
    }
  }

  const sourceCharacters = Array.from(text);
  const validHighlights = annotations
    .filter((item) =>
      item.quote &&
      item.start_offset !== null &&
      item.end_offset !== null &&
      sourceCharacters.slice(item.start_offset, item.end_offset).join("") === item.quote,
    )
    .sort((left, right) => (left.start_offset ?? 0) - (right.start_offset ?? 0));
  const sourceParts: ReactNode[] = [];
  let cursor = 0;
  validHighlights.forEach((item) => {
    const start = item.start_offset ?? 0;
    const end = item.end_offset ?? start;
    if (start < cursor || end > sourceCharacters.length) return;
    if (start > cursor) sourceParts.push(sourceCharacters.slice(cursor, start).join(""));
    sourceParts.push(<mark key={item.annotation_id}>{sourceCharacters.slice(start, end).join("")}</mark>);
    cursor = end;
  });
  if (cursor < sourceCharacters.length) sourceParts.push(sourceCharacters.slice(cursor).join(""));

  return (
    <section className="annotation-editor" aria-label="Source annotations">
      <div className="annotation-heading">
        <div><h3>Read & annotate</h3><p>Select text to highlight it, or add a note on its own.</p></div>
        <span>{annotations.length} saved</span>
      </div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {loading ? <p className="muted compact">Loading source and annotations…</p> : (
        <>
          {text ? (
            <div className="annotation-source" ref={sourceRef}>
              {sourceParts.length ? sourceParts : text}
            </div>
          ) : (
            <p className="muted compact">No extracted text or abstract is available. You can still add a note.</p>
          )}
          {text && (
            <div className="annotation-selection">
              <button className="button secondary small-button" type="button" onMouseDown={(event) => event.preventDefault()} onClick={captureSelection}>Highlight selection</button>
              {selection && <span>Selected: “{selection.quote.slice(0, 180)}{selection.quote.length > 180 ? "…" : ""}”</span>}
            </div>
          )}
          <form className="annotation-form" onSubmit={(event) => void saveAnnotation(event)}>
            <label htmlFor={`annotation-note-${annotationsPath}`}>Note</label>
            <textarea
              id={`annotation-note-${annotationsPath}`}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="What stands out about this passage?"
              maxLength={5000}
              rows={3}
            />
            <button className="button primary small-button" disabled={busy || (!note.trim() && !selection)}>
              {busy ? "Saving…" : "Save annotation"}
            </button>
          </form>
          {!!annotations.length && (
            <div className="annotation-list">
              {annotations.map((item) => (
                <article className="annotation-item" key={item.annotation_id}>
                  {item.quote && <blockquote>{item.quote}</blockquote>}
                  {editingId === item.annotation_id ? (
                    <div className="annotation-edit">
                      <textarea value={editNote} onChange={(event) => setEditNote(event.target.value)} maxLength={5000} rows={2} />
                      <button className="button secondary small-button" type="button" disabled={busy} onClick={() => void updateAnnotation(item)}>Save note</button>
                      <button className="text-button" type="button" onClick={() => setEditingId(null)}>Cancel</button>
                    </div>
                  ) : (
                    <>
                      {item.note && <p>{item.note}</p>}
                      <div className="annotation-actions">
                        <button className="text-button" type="button" onClick={() => { setEditingId(item.annotation_id); setEditNote(item.note); }}>Edit note</button>
                        <button className="text-button danger-text" type="button" disabled={busy} onClick={() => void deleteAnnotation(item)}>Delete</button>
                      </div>
                    </>
                  )}
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default App;
