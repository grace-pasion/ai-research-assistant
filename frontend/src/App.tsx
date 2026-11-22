import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  Download,
  FileText,
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
import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { api, downloadFile, getToken, jsonBody, setToken } from "./api";
import type {
  Conversation,
  DocumentRecord,
  DocumentSearchResult,
  Draft,
  Paper,
  Project,
  SearchResult,
  User,
} from "./types";

type View = "documents" | "papers" | "assistant";
type LoginResponse = { access_token: string; user: User };

function App() {
  const [token, setAuthToken] = useState<string | null>(getToken());
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<View>("documents");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
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

  async function uploadDocument(file: File) {
    if (!project) return;
    if (file.size === 0) {
      setError("Choose a non-empty PDF, DOCX, TXT, or Markdown file.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      await request<DocumentRecord>(`/api/projects/${project.project_id}/documents`, {
        method: "POST",
        body: form,
      });
      await loadProjectData(project);
      setNotice("Upload received. Text extraction is running.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
    } finally {
      setBusy(false);
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
              Password <span className="field-note">{authMode === "register" && "10+ characters"}</span>
              <input
                name="password"
                type="password"
                autoComplete={authMode === "login" ? "current-password" : "new-password"}
                minLength={authMode === "register" ? 10 : 1}
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
                <TabButton active={view === "assistant"} onClick={() => setView("assistant")} icon={<MessageSquareText size={16} />}>Ask & explore</TabButton>
              </div>

              {view === "documents" && (
                <section className="section-content">
                  <div className="section-heading">
                    <div><h2>Research documents</h2><p>Upload source material to make it searchable in your assistant.</p></div>
                    <div className="upload-control">
                      <label className="button primary upload-button">
                        <Upload size={16} /> Add document
                        <input name="file" type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => {
                          const file = event.currentTarget.files?.[0];
                          if (file) void uploadDocument(file);
                          event.currentTarget.value = "";
                        }} />
                      </label>
                    </div>
                  </div>
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
                          <strong>{match.document.filename}</strong><p>{match.excerpt}</p>
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
                            <strong>{document.filename}</strong>
                            <span>{formatBytes(document.file_size)} · {new Date(document.uploaded_at).toLocaleDateString()}</span>
                            {document.processing_error && <small className="inline-error">{document.processing_error}</small>}
                          </div>
                          <StatusPill status={document.processing_status} />
                          <button className="icon-button" title="Download original" onClick={() => void downloadDocument(document)}>
                            <Download size={16} />
                          </button>
                          {document.processing_status !== "processing" && document.processing_status !== "ready" && (
                            <button className="button secondary small-button" onClick={() => void reprocess(document.document_id)}>Reprocess</button>
                          )}
                          <button className="icon-button danger-hover" title="Delete document" onClick={() => void deleteDocument(document.document_id)}>
                            <Trash2 size={16} />
                          </button>
                        </article>
                      ))}
                    </div>
                  )}
                  {processing && <p className="processing-note"><LoaderCircle className="spin" size={15} /> Extracting text and preparing documents…</p>}
                </section>
              )}

              {view === "papers" && (
                <section className="section-content">
                  <div className="section-heading">
                    <div><h2>Discover literature</h2><p>Search scholarly indexes, then save relevant work to this project.</p></div>
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
                    {papers.length ? papers.map((paper) => (
                      <PaperCard key={paper.paper_id} paper={paper} saved onRemove={() => void unsavePaper(paper)} />
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
                          <div className="message-content">{message.content}</div>
                          {message.role === "assistant" && (
                            <>
                              {!!message.sources.length && (
                                <div className="source-list saved-sources">
                                  <span className="source-list-label">CITED SOURCES</span>
                                  {message.sources.map((source, index) => (
                                    <article className="source-card" key={`${source.kind}-${source.source_id}`}>
                                      <span className="source-index">S{index + 1}</span>
                                      <div><strong>{source.title}</strong><p>{source.excerpt}</p></div>
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
                          <div className="message-content">{draft.answer}</div>
                          {!!draft.sources.length && (
                            <div className="source-list">
                              <span className="source-list-label">SOURCES TO REVIEW</span>
                              {draft.sources.map((source, index) => (
                                <article className="source-card" key={`${source.kind}-${source.source_id}`}>
                                  <span className="source-index">S{index + 1}</span>
                                  <div><strong>{source.title}</strong><p>{source.excerpt}</p></div>
                                  {source.kind === "paper" && source.paper_id && papers.find((paper) => paper.paper_id === source.paper_id)?.paper_url && (
                                    <a className="source-link" href={papers.find((paper) => paper.paper_id === source.paper_id)?.paper_url ?? undefined} target="_blank" rel="noreferrer" aria-label="Open cited paper"><ArrowUpRight size={15} /></a>
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
                        placeholder="Ask about your documents and saved papers…"
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
    processing: "Processing",
    ready: "Ready",
    needs_api_key: "Needs API key",
    failed: "Failed",
  };
  return <span className={`status-pill status-${status}`}>{status === "processing" && <LoaderCircle size={12} className="spin" />}{labels[status] ?? status}</span>;
}

function PaperCard({ paper, saved = false, onSave, onRemove }: { paper: Paper; saved?: boolean; onSave?: () => void; onRemove?: () => void }) {
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
      </div>
      <div className="paper-actions">
        {paper.paper_url && <a className="icon-button" href={paper.paper_url} target="_blank" rel="noreferrer" title="Open paper"><ArrowUpRight size={16} /></a>}
        {saved ? (
          <button className="button secondary small-button" onClick={onRemove}><X size={14} /> Remove</button>
        ) : (
          <button className="button secondary small-button" onClick={onSave}><Plus size={15} /> Save</button>
        )}
      </div>
    </article>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default App;
