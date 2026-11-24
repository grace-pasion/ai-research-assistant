import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Bell,
  Check,
  ChevronDown,
  Download,
  Eye,
  EyeOff,
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
  Settings,
  Share2,
  ShieldCheck,
  Trash2,
  Upload,
  Users,
  X,
} from "lucide-react";
import { Fragment, type FormEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, downloadFile, fetchPdfObjectUrl, getToken, jsonBody, setToken } from "./api";
import {
  InboxDialog,
  ShareDialog,
  TeamChannelDialog,
  TeamWorkspaceDialog,
} from "./Collaboration";
import { LatexWorkspace } from "./LatexWorkspace";
import { fetchProjectData } from "./projectData";
import {
  filterAndSortScreeningPapers,
  type ScreeningSort,
  type ScreeningStatusFilter,
} from "./literatureScreening";
import {
  filterProjectAnnotations,
  formatSelectedAnnotations,
  type AnnotationSort,
  type AnnotationSourceFilter,
} from "./projectAnnotations";
import type {
  AIUsageResponse,
  Annotation,
  BulkDocumentUploadResponse,
  Conversation,
  DocumentRecord,
  DocumentSearchResult,
  Draft,
  Message,
  PaperImportResponse,
  Paper,
  ProjectAnnotation,
  Project,
  SavedPaperSearch,
  SavedPaperSearchRun,
  SearchResult,
  Source,
  SystematicReview,
  TeamWorkspace,
  User,
} from "./types";

type View = "documents" | "papers" | "notes" | "latex" | "assistant";
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

function retainProjectSelection(current: Project | null, loaded: Project[]): Project | null {
  if (!current) return loaded[0] ?? null;
  const updated = loaded.find((item) => item.project_id === current.project_id);
  if (!updated) return loaded[0] ?? null;
  if (updated.project_name === current.project_name
    && updated.description === current.description
    && updated.updated_at === current.updated_at) return current;
  return updated;
}

function projectsInWorkspace(
  projects: Project[],
  workspaceId: string | null,
  workspaces: TeamWorkspace[],
): Project[] {
  if (workspaceId) {
    return projects.filter((item) => item.team_workspace_id === workspaceId);
  }
  const memberWorkspaceIds = new Set(workspaces.map((item) => item.team_workspace_id));
  return projects.filter((item) =>
    item.team_workspace_id === null || !memberWorkspaceIds.has(item.team_workspace_id),
  );
}

function App() {
  const [token, setAuthToken] = useState<string | null>(getToken());
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [teamWorkspaces, setTeamWorkspaces] = useState<TeamWorkspace[]>([]);
  const [selectedTeamWorkspaceId, setSelectedTeamWorkspaceId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<View>("documents");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [aiUsage, setAiUsage] = useState<AIUsageResponse | null>(null);
  const [bulkUploads, setBulkUploads] = useState<UploadQueueItem[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [annotationDocumentId, setAnnotationDocumentId] = useState<string | null>(null);
  const [citationPage, setCitationPage] = useState<number | null>(null);
  const [citationExcerpt, setCitationExcerpt] = useState<string | null>(null);
  const [annotationPaperId, setAnnotationPaperId] = useState<string | null>(null);
  const [projectAnnotations, setProjectAnnotations] = useState<ProjectAnnotation[]>([]);
  const [annotationQuery, setAnnotationQuery] = useState("");
  const [annotationSourceFilter, setAnnotationSourceFilter] = useState<AnnotationSourceFilter>("all");
  const [annotationSort, setAnnotationSort] = useState<AnnotationSort>("newest");
  const [selectedAnnotationIds, setSelectedAnnotationIds] = useState<Set<string>>(() => new Set());
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentMatches, setDocumentMatches] = useState<DocumentSearchResult[] | null>(null);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [systematicReview, setSystematicReview] = useState<SystematicReview | null>(null);
  const [reviewQuestion, setReviewQuestion] = useState("");
  const [reviewProtocol, setReviewProtocol] = useState("");
  const [reviewSaveBusy, setReviewSaveBusy] = useState(false);
  const [reviewConflict, setReviewConflict] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewLoadError, setReviewLoadError] = useState("");
  const [reviewReloadKey, setReviewReloadKey] = useState(0);
  const [screeningFilter, setScreeningFilter] = useState<ScreeningStatusFilter>("all");
  const [screeningQuery, setScreeningQuery] = useState("");
  const [screeningSort, setScreeningSort] = useState<ScreeningSort>("saved");
  const [selectedPaperIds, setSelectedPaperIds] = useState<Set<string>>(() => new Set());
  const [bulkScreeningStatus, setBulkScreeningStatus] =
    useState<Paper["screening_status"]>("include");
  const [screeningBusy, setScreeningBusy] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [savedPaperSearches, setSavedPaperSearches] = useState<SavedPaperSearch[]>([]);
  const [saveSearchAlerts, setSaveSearchAlerts] = useState(false);
  const [savedSearchBusy, setSavedSearchBusy] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [showNewProject, setShowNewProject] = useState(false);
  const [showEditProject, setShowEditProject] = useState(false);
  const [showShareProject, setShowShareProject] = useState(false);
  const [showProjectExport, setShowProjectExport] = useState(false);
  const [includeOriginalDocuments, setIncludeOriginalDocuments] = useState(false);
  const [includeConversations, setIncludeConversations] = useState(false);
  const [projectExportBusy, setProjectExportBusy] = useState(false);
  const [projectExportError, setProjectExportError] = useState("");
  const [showInbox, setShowInbox] = useState(false);
  const [showTeamWorkspaces, setShowTeamWorkspaces] = useState(false);
  const [showTeamChannels, setShowTeamChannels] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [searchText, setSearchText] = useState("");
  const [provider, setProvider] = useState("openalex");
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [briefExportingMessageId, setBriefExportingMessageId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [askMode, setAskMode] = useState<"question" | "compare" | "directions">("question");
  const selectedProjectIdRef = useRef<string | null>(null);
  const canEditProject = project?.access_role === "owner" || project?.access_role === "edit";
  const canCommentOnProject = canEditProject || project?.access_role === "comment";

  useEffect(() => {
    setSelectedPaperIds(new Set());
    setSelectedAnnotationIds(new Set());
  }, [project?.project_id]);

  const request = useCallback(
    async <T,>(path: string, options?: RequestInit) => api<T>(path, options, token),
    [token],
  );

  const refreshTeamWorkspaces = useCallback(async (selectWorkspaceId?: string) => {
    const loaded = await request<TeamWorkspace[]>("/api/team-workspaces");
    setTeamWorkspaces(loaded);
    if (selectWorkspaceId) {
      setSelectedTeamWorkspaceId(selectWorkspaceId);
      const loadedProjects = await request<Project[]>("/api/projects");
      setProjects(loadedProjects);
      setProject((current) => retainProjectSelection(
        current,
        loadedProjects.filter((item) => item.team_workspace_id === selectWorkspaceId),
      ));
    }
  }, [request]);

  const refreshProjects = useCallback(async () => {
    const loaded = await request<Project[]>("/api/projects");
    setProjects(loaded);
    setProject((selected) => retainProjectSelection(
      selected,
      projectsInWorkspace(loaded, selectedTeamWorkspaceId, teamWorkspaces),
    ));
  }, [request, selectedTeamWorkspaceId, teamWorkspaces]);

  const refreshUnreadCount = useCallback(async () => {
    const result = await request<{ count: number }>("/api/inbox/unread-count");
    setUnreadCount(result.count);
  }, [request]);

  const refreshUsage = useCallback(async () => {
    try {
      setAiUsage(await request<AIUsageResponse>("/api/usage"));
    } catch (cause) {
      setAiUsage(null);
      setError((current) => current || (
        cause instanceof Error ? cause.message : "Could not load daily AI usage."
      ));
    }
  }, [request]);

  const loadProjectData = useCallback(
    async (selected: Project) => {
      const id = selected.project_id;
      await fetchProjectData(
        id,
        request,
        () => selectedProjectIdRef.current === id,
        ({ documents: docs, papers: savedPapers, conversations: chats }) => {
          setDocuments(docs);
          setPapers(savedPapers);
          setConversations(chats);
          void refreshUsage();
        },
      );
    },
    [refreshUsage, request],
  );

  useEffect(() => {
    if (!token) return;
    let active = true;
    Promise.all([
      request<User>("/api/auth/me"),
      request<Project[]>("/api/projects"),
      request<TeamWorkspace[]>("/api/team-workspaces"),
    ])
      .then(([me, loaded, loadedWorkspaces]) => {
        if (!active) return;
        setUser(me);
        setProjects(loaded);
        setTeamWorkspaces(loadedWorkspaces);
        const personalProjects = projectsInWorkspace(loaded, null, loadedWorkspaces);
        const initialWorkspaceId = personalProjects.length
          ? null
          : loadedWorkspaces[0]?.team_workspace_id ?? null;
        setSelectedTeamWorkspaceId(initialWorkspaceId);
        setProject(projectsInWorkspace(loaded, initialWorkspaceId, loadedWorkspaces)[0] ?? null);
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

  useLayoutEffect(() => {
    selectedProjectIdRef.current = project?.project_id ?? null;
    setDocuments([]);
    setPapers([]);
    setSystematicReview(null);
    setReviewQuestion("");
    setReviewProtocol("");
    setReviewSaveBusy(false);
    setReviewConflict(false);
    setReviewLoading(false);
    setReviewLoadError("");
    setShowProjectExport(false);
    setProjectExportBusy(false);
    setProjectExportError("");
    setProjectAnnotations([]);
    setSavedPaperSearches([]);
    setConversations([]);
    setAiUsage(null);
  }, [project?.project_id, token]);

  useEffect(() => {
    if (!project || !token || view !== "notes") return;
    let active = true;
    const loadAnnotations = () => {
      request<ProjectAnnotation[]>(`/api/projects/${project.project_id}/annotations`)
        .then((loaded) => {
          if (active) setProjectAnnotations(loaded);
        })
        .catch((cause: unknown) => {
          if (active) setError(cause instanceof Error ? cause.message : "Could not load project notes.");
        });
    };
    loadAnnotations();
    const timer = window.setInterval(loadAnnotations, 30_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [project?.project_id, request, token, view]);

  useEffect(() => {
    if (!project || !token) {
      setDocuments([]);
      setPapers([]);
      setSavedPaperSearches([]);
      setConversations([]);
      setAiUsage(null);
      return;
    }
    let active = true;
    loadProjectData(project).catch((cause: unknown) => {
      if (!active || selectedProjectIdRef.current !== project.project_id) return;
      setError(cause instanceof Error ? cause.message : "Could not load the project.");
    });
    return () => {
      active = false;
    };
  }, [loadProjectData, project, token]);

  useEffect(() => {
    if (!project || !token) return;
    const projectId = project.project_id;
    let active = true;
    setReviewLoading(true);
    setReviewLoadError("");
    request<SystematicReview>(`/api/projects/${projectId}/papers/review`)
      .then((loaded) => {
        if (!active || selectedProjectIdRef.current !== projectId) return;
        setSystematicReview(loaded);
        setReviewQuestion(loaded.review_question);
        setReviewProtocol(loaded.protocol);
        setReviewConflict(false);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setReviewLoadError(cause instanceof Error ? cause.message : "Could not load the review workspace.");
      })
      .finally(() => {
        if (active) setReviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project?.project_id, request, reviewReloadKey, token]);

  useEffect(() => {
    if (!project || !token) return;
    let active = true;
    const path = `/api/projects/${project.project_id}/papers/saved-searches`;
    request<SavedPaperSearch[]>(path)
      .then((saved) => {
        if (active) setSavedPaperSearches(saved);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load saved searches.");
      });
    const checkAlerts = () => {
      request<{ checked_count: number; notifications_created: number }>(
        `${path}/check-alerts`,
        { method: "POST" },
      )
        .then(async (result) => {
          if (!active) return;
          if (result.notifications_created) await refreshUnreadCount();
        })
        .catch((cause: unknown) => {
          if (active) setError((current) => current || (
            cause instanceof Error ? cause.message : "Could not check saved search alerts."
          ));
        });
    };
    void checkAlerts();
    const timer = window.setInterval(checkAlerts, 15 * 60 * 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [project?.project_id, refreshUnreadCount, request, token]);

  const processing = useMemo(
    () => documents.some((document) => document.processing_status === "processing"),
    [documents],
  );
  const processingStatusCounts = useMemo(() => ({
    processing: documents.filter((document) => document.processing_status === "processing").length,
    failed: documents.filter((document) => document.processing_status === "failed").length,
    quotaExceeded: documents.filter((document) => document.processing_status === "quota_exceeded").length,
    needsApiKey: documents.filter((document) => document.processing_status === "needs_api_key").length,
  }), [documents]);
  const screeningCounts = useMemo(() => ({
    unread: papers.filter((paper) => paper.screening_status === "unread").length,
    undecided: papers.filter((paper) => paper.screening_status === "undecided").length,
    include: papers.filter((paper) => paper.screening_status === "include").length,
    exclude: papers.filter((paper) => paper.screening_status === "exclude").length,
  }), [papers]);
  const reviewedPaperCount = screeningCounts.undecided + screeningCounts.include + screeningCounts.exclude;
  const reviewDirty = systematicReview !== null && (
    reviewQuestion !== systematicReview.review_question
    || reviewProtocol !== systematicReview.protocol
  );
  const visibleScreeningPapers = useMemo(
    () => filterAndSortScreeningPapers(papers, screeningFilter, screeningQuery, screeningSort),
    [papers, screeningFilter, screeningQuery, screeningSort],
  );
  const selectedScreeningCount = papers.filter((paper) => selectedPaperIds.has(paper.paper_id)).length;
  const visibleProjectAnnotations = useMemo(
    () => filterProjectAnnotations(
      projectAnnotations,
      annotationQuery,
      annotationSourceFilter,
      annotationSort,
    ),
    [annotationQuery, annotationSourceFilter, annotationSort, projectAnnotations],
  );
  const selectedProjectAnnotationCount = projectAnnotations
    .filter((annotation) => selectedAnnotationIds.has(annotation.annotation_id)).length;
  const allVisibleAnnotationsSelected = visibleProjectAnnotations.length > 0
    && visibleProjectAnnotations.every((annotation) => selectedAnnotationIds.has(annotation.annotation_id));
  const allVisibleScreeningPapersSelected = visibleScreeningPapers.length > 0
    && visibleScreeningPapers.every((paper) => selectedPaperIds.has(paper.paper_id));
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

  function openProjectAnnotation(annotation: ProjectAnnotation) {
    if (annotation.document_id) {
      openDocumentEvidence(annotation.document_id);
      return;
    }
    if (annotation.paper_id) {
      setScreeningQuery(annotation.source_title);
      setScreeningFilter("all");
      setAnnotationPaperId(annotation.paper_id);
      setView("papers");
    }
  }

  function toggleAnnotationSelection(annotationId: string, selected: boolean) {
    setSelectedAnnotationIds((current) => {
      const next = new Set(current);
      if (selected) next.add(annotationId);
      else next.delete(annotationId);
      return next;
    });
  }

  function useSelectedAnnotationsInAssistant() {
    const baseQuestion = question.trim() || "Compare the selected notes with my project sources.";
    const remainingChars = Math.max(0, 5000 - baseQuestion.length - 2);
    const formatted = formatSelectedAnnotations(
      projectAnnotations,
      selectedAnnotationIds,
      remainingChars,
    );
    if (!formatted.includedCount) {
      setError("The selected notes do not fit in the assistant prompt. Shorten the prompt or select fewer notes.");
      return;
    }
    setError("");
    setNotice(formatted.omittedCount
      ? `${formatted.includedCount} selected notes added; ${formatted.omittedCount} did not fit.`
      : `${formatted.includedCount} selected ${formatted.includedCount === 1 ? "note" : "notes"} added to the comparison prompt.`);
    setAskMode("compare");
    setQuestion(`${baseQuestion}\n\n${formatted.text}`);
    setSelectedAnnotationIds(new Set());
    setView("assistant");
  }

  function openSource(source: Source) {
    if (source.kind === "document" && source.document_id) {
      openDocumentEvidence(source.document_id, source.page_number, source.excerpt);
    } else if (source.paper_url) {
      window.open(source.paper_url, "_blank", "noopener,noreferrer");
    }
  }

  function togglePaperSelection(paperId: string, selected: boolean) {
    setSelectedPaperIds((current) => {
      const next = new Set(current);
      if (selected) next.add(paperId);
      else next.delete(paperId);
      return next;
    });
  }

  function toggleVisiblePaperSelection() {
    setSelectedPaperIds((current) => {
      const next = new Set(current);
      for (const paper of visibleScreeningPapers) {
        if (allVisibleScreeningPapersSelected) next.delete(paper.paper_id);
        else next.add(paper.paper_id);
      }
      return next;
    });
  }

  async function bulkUpdatePaperScreening() {
    if (!project || screeningBusy) return;
    const paperIds = papers
      .filter((paper) => selectedPaperIds.has(paper.paper_id))
      .map((paper) => paper.paper_id);
    if (!paperIds.length) return;
    setScreeningBusy(true);
    setError("");
    try {
      const result = await request<{ updated_count: number }>(
        `/api/projects/${project.project_id}/papers/screening/bulk`,
        {
          method: "POST",
          body: jsonBody({ paper_ids: paperIds, screening_status: bulkScreeningStatus }),
        },
      );
      const updatedPaperIds = new Set(paperIds);
      setPapers((current) => current.map((paper) =>
        updatedPaperIds.has(paper.paper_id)
          ? { ...paper, screening_status: bulkScreeningStatus }
          : paper,
      ));
      setSelectedPaperIds(new Set());
      setNotice(`Updated ${result.updated_count} screening decision${result.updated_count === 1 ? "" : "s"}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not apply bulk screening decisions.");
    } finally {
      setScreeningBusy(false);
    }
  }

  async function exportScreeningCsv() {
    if (!project || !papers.length || referenceBusy) return;
    setReferenceBusy(true);
    setError("");
    try {
      await downloadFile(
        `/api/projects/${project.project_id}/papers/screening/export`,
        "screening.csv",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not export screening decisions.");
    } finally {
      setReferenceBusy(false);
    }
  }

  async function saveSystematicReview() {
    if (!project || !systematicReview || !canEditProject || reviewSaveBusy || !reviewDirty) return;
    const projectId = project.project_id;
    setReviewSaveBusy(true);
    setReviewConflict(false);
    setError("");
    setNotice("");
    try {
      const saved = await request<SystematicReview>(
        `/api/projects/${projectId}/papers/review`,
        {
          method: "PUT",
          body: jsonBody({
            review_question: reviewQuestion,
            protocol: reviewProtocol,
            expected_updated_at: systematicReview.updated_at,
          }),
        },
      );
      if (selectedProjectIdRef.current !== projectId) return;
      setSystematicReview(saved);
      setReviewQuestion(saved.review_question);
      setReviewProtocol(saved.protocol);
      setNotice("Review question and protocol saved for this project.");
    } catch (cause) {
      if (selectedProjectIdRef.current !== projectId) return;
      const message = cause instanceof Error ? cause.message : "Could not save the review protocol.";
      setReviewConflict(message.includes("changed in another session"));
      setError(message);
    } finally {
      if (selectedProjectIdRef.current === projectId) setReviewSaveBusy(false);
    }
  }

  async function exportSystematicReview() {
    if (!project || !systematicReview || reviewDirty || referenceBusy) return;
    setReferenceBusy(true);
    setError("");
    try {
      await downloadFile(
        `/api/projects/${project.project_id}/papers/review/export`,
        "systematic-review-report.csv",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not export the systematic review report.");
    } finally {
      setReferenceBusy(false);
    }
  }

  function openProjectExport() {
    setError("");
    setNotice("");
    setProjectExportError("");
    setIncludeOriginalDocuments(false);
    setIncludeConversations(false);
    setShowProjectExport(true);
  }

  async function exportProjectBundle() {
    if (!project || projectExportBusy) return;
    const projectId = project.project_id;
    setProjectExportBusy(true);
    setProjectExportError("");
    setError("");
    setNotice("");
    const params = new URLSearchParams({
      include_original_documents: String(includeOriginalDocuments),
      include_conversations: String(includeConversations),
    });
    try {
      await downloadFile(
        `/api/projects/${projectId}/export?${params.toString()}`,
        "project-backup.zip",
      );
      if (selectedProjectIdRef.current !== projectId) return;
      setShowProjectExport(false);
      setNotice("Project backup downloaded.");
    } catch (cause) {
      if (selectedProjectIdRef.current !== projectId) return;
      setProjectExportError(cause instanceof Error ? cause.message : "Could not export this project.");
    } finally {
      if (selectedProjectIdRef.current === projectId) setProjectExportBusy(false);
    }
  }

  useEffect(() => {
    if (!processing || !project) return;
    const timer = window.setInterval(() => {
      request<DocumentRecord[]>(`/api/projects/${project.project_id}/documents`)
        .then((loaded) => {
          if (selectedProjectIdRef.current !== project.project_id) return;
          setDocuments(loaded);
          void refreshUsage();
        })
        .catch((cause: unknown) =>
          setError(cause instanceof Error ? cause.message : "Could not refresh document status."),
        );
    }, 2500);
    return () => window.clearInterval(timer);
  }, [processing, project, refreshUsage, request]);

  useEffect(() => {
    if (!token) {
      setUnreadCount(0);
      return;
    }
    const refresh = () => refreshUnreadCount().catch((cause: unknown) =>
      setError((current) => current || (
        cause instanceof Error ? cause.message : "Could not refresh inbox notifications."
      )),
    );
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [refreshUnreadCount, token]);

  useEffect(() => {
    if (!project || !token) return;
    let active = true;
    const refreshSharedProject = async () => {
      try {
        const [loadedProjects, docs, savedPapers, chats] = await Promise.all([
          request<Project[]>("/api/projects"),
          request<DocumentRecord[]>(`/api/projects/${project.project_id}/documents`),
          request<Paper[]>(`/api/projects/${project.project_id}/papers`),
          request<Conversation[]>(`/api/projects/${project.project_id}/assistant/conversations`),
        ]);
        if (!active || selectedProjectIdRef.current !== project.project_id) return;
        setProjects(loadedProjects);
        setProject((selected) => retainProjectSelection(selected, loadedProjects));
        setDocuments(docs);
        setPapers(savedPapers);
        setConversations(chats);
      } catch (cause) {
        if (!active) return;
        setError((current) => current || (
          cause instanceof Error ? cause.message : "Could not refresh shared project updates."
        ));
      }
    };
    const timer = window.setInterval(() => void refreshSharedProject(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [project, request, token]);

  useEffect(() => {
    if (!aiUsage) return;
    const delay = Date.parse(aiUsage.resets_at) - Date.now();
    if (delay <= 0) {
      void refreshUsage();
      return;
    }
    const timer = window.setTimeout(() => void refreshUsage(), delay + 1000);
    return () => window.clearTimeout(timer);
  }, [aiUsage?.resets_at, refreshUsage]);

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
    if (authMode === "register") {
      body.name = String(form.get("name") ?? "");
      body.username = String(form.get("username") ?? "");
    }
    try {
      const result = await api<LoginResponse>(
        `/api/auth/${authMode === "register" ? "register" : "login"}`,
        { method: "POST", body: jsonBody(body) },
        null,
      );
      setToken(result.access_token);
      setAuthToken(result.access_token);
      setUser(result.user);
      const [loaded, loadedWorkspaces] = await Promise.all([
        api<Project[]>("/api/projects", {}, result.access_token),
        api<TeamWorkspace[]>("/api/team-workspaces", {}, result.access_token),
      ]);
      setProjects(loaded);
      setTeamWorkspaces(loadedWorkspaces);
      const personalProjects = projectsInWorkspace(loaded, null, loadedWorkspaces);
      const initialWorkspaceId = personalProjects.length
        ? null
        : loadedWorkspaces[0]?.team_workspace_id ?? null;
      setSelectedTeamWorkspaceId(initialWorkspaceId);
      setProject(projectsInWorkspace(loaded, initialWorkspaceId, loadedWorkspaces)[0] ?? null);
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
          team_workspace_id: selectedTeamWorkspaceId,
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

  async function runPaperSearch(queryText: string, searchProvider: string) {
    if (!project || queryText.trim().length < 2 || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await request<SearchResult>(
        `/api/projects/${project.project_id}/papers/search?q=${encodeURIComponent(queryText.trim())}&provider=${searchProvider}&limit=10`,
      );
      setSearchResults(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Academic search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function searchPapers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runPaperSearch(searchText, provider);
  }

  async function savePaperSearch(result: SearchResult) {
    if (!project || savedSearchBusy) return;
    setSavedSearchBusy(true);
    setError("");
    try {
      const saved = await request<SavedPaperSearch>(
        `/api/projects/${project.project_id}/papers/saved-searches`,
        {
          method: "POST",
          body: jsonBody({ query_id: result.query_id, alert_enabled: saveSearchAlerts }),
        },
      );
      setSavedPaperSearches((current) => [
        saved,
        ...current.filter((item) => item.saved_search_id !== saved.saved_search_id),
      ]);
      setNotice("Search saved for this project.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this search.");
    } finally {
      setSavedSearchBusy(false);
    }
  }

  async function rerunSavedPaperSearch(saved: SavedPaperSearch) {
    if (!project || busy) return;
    setSearchText(saved.query_text);
    setProvider(saved.api_provider);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<SavedPaperSearchRun>(
        `/api/projects/${project.project_id}/papers/saved-searches/${saved.saved_search_id}/run`,
        { method: "POST" },
      );
      setSearchResults(result);
      if (result.new_result_count > 0) {
        setNotice(`Found ${result.new_result_count} new result${result.new_result_count === 1 ? "" : "s"}.`);
        if (saved.alert_enabled) await refreshUnreadCount();
      } else {
        setNotice("Search rerun; no new results were found.");
      }
      setSavedPaperSearches((current) => current.map((item) =>
        item.saved_search_id === saved.saved_search_id
          ? { ...item, last_checked_at: new Date().toISOString() }
          : item,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not rerun this saved search.");
    } finally {
      setBusy(false);
    }
  }

  async function setSavedSearchAlerts(saved: SavedPaperSearch, alertEnabled: boolean) {
    if (!project || savedSearchBusy) return;
    setSavedSearchBusy(true);
    setError("");
    try {
      const updated = await request<SavedPaperSearch>(
        `/api/projects/${project.project_id}/papers/saved-searches/${saved.saved_search_id}`,
        { method: "PATCH", body: jsonBody({ alert_enabled: alertEnabled }) },
      );
      setSavedPaperSearches((current) => current.map((item) =>
        item.saved_search_id === updated.saved_search_id ? updated : item,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update saved search alerts.");
    } finally {
      setSavedSearchBusy(false);
    }
  }

  async function removeSavedPaperSearch(saved: SavedPaperSearch) {
    if (!project || savedSearchBusy) return;
    setSavedSearchBusy(true);
    setError("");
    try {
      await request<void>(
        `/api/projects/${project.project_id}/papers/saved-searches/${saved.saved_search_id}`,
        { method: "DELETE" },
      );
      setSavedPaperSearches((current) =>
        current.filter((item) => item.saved_search_id !== saved.saved_search_id),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove this saved search.");
    } finally {
      setSavedSearchBusy(false);
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

  async function exportResearchBrief(message: Message) {
    if (!project || !conversation || briefExportingMessageId) return;
    setBriefExportingMessageId(message.message_id);
    setError("");
    setNotice("");
    try {
      await downloadFile(
        `/api/projects/${project.project_id}/assistant/conversations/${conversation.conversation_id}/brief?message_id=${encodeURIComponent(message.message_id)}`,
        "research-brief.docx",
      );
      setNotice("Cited research brief downloaded as a Word document.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not export the research brief.");
    } finally {
      setBriefExportingMessageId(null);
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
    if (!project || question.trim().length < 3 || aiUsage?.assistant_prompts_remaining === 0) return;
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
      void refreshUsage();
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
      setProject(
        projectsInWorkspace(remaining, selectedTeamWorkspaceId, teamWorkspaces)[0] ?? null,
      );
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
    setTeamWorkspaces([]);
    setSelectedTeamWorkspaceId(null);
    setProject(null);
    setConversation(null);
    setDraft(null);
    setError("");
  }

  function switchTeamWorkspace(workspaceId: string | null) {
    setSelectedTeamWorkspaceId(workspaceId);
    setProject((current) => retainProjectSelection(
      current,
      projectsInWorkspace(projects, workspaceId, teamWorkspaces),
    ));
    setConversation(null);
    setDraft(null);
    setView("documents");
  }

  const visibleProjects = useMemo(
    () => projectsInWorkspace(projects, selectedTeamWorkspaceId, teamWorkspaces),
    [projects, selectedTeamWorkspaceId, teamWorkspaces],
  );
  const channelWorkspaceId = selectedTeamWorkspaceId ?? project?.team_workspace_id ?? null;
  const channelWorkspace = teamWorkspaces.find(
    (item) => item.team_workspace_id === channelWorkspaceId,
  );
  const canCreateTeamChannel = Boolean(channelWorkspace);

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
              <>
                <label>
                  Name
                  <input name="name" autoComplete="name" required maxLength={120} />
                </label>
                <label>
                  Username <span className="field-note">3–32 letters, numbers, dots, underscores, or hyphens</span>
                  <input name="username" autoComplete="username" required minLength={3} maxLength={32} pattern="([A-Za-z0-9._]|-)+" />
                </label>
              </>
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
          <FolderPlus size={16} /> New {selectedTeamWorkspaceId ? "team project" : "project"} <Plus size={15} className="push-right" />
        </button>
        <div className="sidebar-team-heading">
          <span className="sidebar-label">TEAM WORKSPACES</span>
          <button className="icon-button" title="Manage team workspaces" onClick={() => setShowTeamWorkspaces(true)}>
            <Plus size={15} />
          </button>
        </div>
        <nav className="team-workspace-list" aria-label="Team workspaces">
          <button
            className={`team-workspace-link ${selectedTeamWorkspaceId === null ? "selected" : ""}`}
            onClick={() => switchTeamWorkspace(null)}
            type="button"
          >
            <Users size={14} /><span>Personal &amp; shared</span>
          </button>
          {teamWorkspaces.map((workspace) => (
            <button
              className={`team-workspace-link ${selectedTeamWorkspaceId === workspace.team_workspace_id ? "selected" : ""}`}
              key={workspace.team_workspace_id}
              onClick={() => switchTeamWorkspace(workspace.team_workspace_id)}
              type="button"
            >
              <Users size={14} /><span>{workspace.name}</span>
            </button>
          ))}
        </nav>
        <nav className="project-list" aria-label="Research projects">
          {visibleProjects.map((item) => (
            <button
              className={`project-link ${project?.project_id === item.project_id ? "selected" : ""}`}
              key={item.project_id}
              onClick={() => {
                const memberWorkspace = teamWorkspaces.find(
                  (workspace) => workspace.team_workspace_id === item.team_workspace_id,
                );
                setSelectedTeamWorkspaceId(memberWorkspace ? memberWorkspace.team_workspace_id : null);
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
          {!visibleProjects.length && <p className="sidebar-empty">No projects here yet.</p>}
        </nav>
        <div className="sidebar-spacer" />
        <div className="account-card">
          <button
            className="account-open"
            aria-label="Open account settings"
            title="Account settings"
            onClick={() => {
              setShowAccountSettings(true);
              void refreshUsage();
            }}
          >
            <span className="avatar">
              {user.profile_picture
                ? <img src={user.profile_picture} alt="" />
                : user.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="account-name">
              <strong>{user.name}</strong>
              <small>@{user.username}</small>
            </span>
            <Settings size={15} aria-hidden="true" />
          </button>
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
            <span className="private-badge">
              {project?.team_workspace_id
                ? <><Users size={14} /> Team workspace</>
                : project && user && project.user_id !== user.user_id
                  ? <><Users size={14} /> Shared project</>
                  : <><ShieldCheck size={14} /> Private workspace</>}
            </span>
            <button className="icon-button inbox-button" title="Inbox and messages" onClick={() => setShowInbox(true)}>
              <Bell size={17} />
              {unreadCount > 0 && <span className="unread-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>}
            </button>
            {channelWorkspaceId && (
              <button
                className="icon-button"
                title="Team channels"
                onClick={() => setShowTeamChannels(true)}
              >
                <MessageSquareText size={16} />
              </button>
            )}
            <button
              className="icon-button"
              title="Team workspaces"
              onClick={() => setShowTeamWorkspaces(true)}
            >
              <Users size={16} />
            </button>
            {project && (
              <>
                {user && project.user_id === user.user_id && (
                  <button className="icon-button" title="Share project" onClick={() => setShowShareProject(true)}>
                    <Share2 size={16} />
                  </button>
                )}
                {user && project.user_id === user.user_id && (
                  <button className="icon-button danger-hover" title="Delete project" onClick={deleteProject}>
                    <Trash2 size={16} />
                  </button>
                )}
              </>
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
                  <div><p className="eyebrow">{selectedTeamWorkspaceId ? "TEAM WORKSPACE" : "WORKSPACE"}</p><h2>New {selectedTeamWorkspaceId ? "team " : ""}research project</h2></div>
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
          {showShareProject && project && (
            <ShareDialog
              project={project}
              request={request}
              onClose={() => setShowShareProject(false)}
            />
          )}
          {showProjectExport && project && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget && !projectExportBusy) {
                setShowProjectExport(false);
              }
            }}>
              <section
                className="modal-card project-export-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="project-export-title"
              >
                <div className="modal-heading">
                  <div>
                    <p className="eyebrow">PROJECT BACKUP</p>
                    <h2 id="project-export-title">Export project bundle</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setShowProjectExport(false)}
                    aria-label="Close"
                    disabled={projectExportBusy}
                  >
                    <X size={18} />
                  </button>
                </div>
                <p className="muted">
                  The ZIP always includes project details, references, notes, writing files,
                  review protocol, and a document inventory. Choose whether to include the
                  original files or your assistant conversations.
                </p>
                {projectExportError && (
                  <p className="project-export-error" role="alert">{projectExportError}</p>
                )}
                <label className="project-export-option">
                  <input
                    type="checkbox"
                    checked={includeOriginalDocuments}
                    onChange={(event) => setIncludeOriginalDocuments(event.target.checked)}
                    disabled={projectExportBusy}
                  />
                  <span>
                    <strong>Original uploaded documents</strong>
                    <small>Include copies of the files stored for this project. The ZIP may be large.</small>
                  </span>
                </label>
                <label className="project-export-option">
                  <input
                    type="checkbox"
                    checked={includeConversations}
                    onChange={(event) => setIncludeConversations(event.target.checked)}
                    disabled={projectExportBusy}
                  />
                  <span>
                    <strong>My assistant conversations</strong>
                    <small>Includes only conversations you authored; collaborators’ histories stay private.</small>
                  </span>
                </label>
                <div className="project-export-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setShowProjectExport(false)}
                    disabled={projectExportBusy}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button primary"
                    onClick={() => void exportProjectBundle()}
                    disabled={projectExportBusy}
                  >
                    <Download size={15} />
                    {projectExportBusy ? "Preparing ZIP…" : "Download project ZIP"}
                  </button>
                </div>
              </section>
            </div>
          )}
          {showInbox && (
            <InboxDialog
              request={request}
              onClose={() => setShowInbox(false)}
              onProjectsUpdated={refreshProjects}
              onUnreadCount={refreshUnreadCount}
            />
          )}
          {showTeamWorkspaces && (
            <TeamWorkspaceDialog
              workspaces={teamWorkspaces}
              userId={user.user_id}
              request={request}
              onClose={() => setShowTeamWorkspaces(false)}
              onChanged={refreshTeamWorkspaces}
            />
          )}
          {showTeamChannels && channelWorkspaceId && (
            <TeamChannelDialog
              workspaceId={channelWorkspaceId}
              workspaceName={channelWorkspace?.name ?? "Shared team workspace"}
              project={project?.team_workspace_id === channelWorkspaceId ? project : null}
              canCreate={canCreateTeamChannel}
              request={request}
              onClose={() => setShowTeamChannels(false)}
            />
          )}
          {showAccountSettings && (
            <AccountSettingsDialog
              user={user}
              aiUsage={aiUsage}
              processingStatusCounts={processingStatusCounts}
              request={request}
              onUserUpdated={setUser}
              onClose={() => setShowAccountSettings(false)}
            />
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
                  <span className="project-access-role">
                    {{ owner: "Owner", read: "Reader", comment: "Commenter", edit: "Editor" }[project.access_role]} access
                  </span>
                </div>
                <div className="project-stat">
                  <span>{documents.length}</span><small>documents</small>
                  <i />
                  <span>{papers.length}</span><small>saved papers</small>
                </div>
                <div className="project-heading-actions">
                  <button className="button secondary small-button" onClick={openProjectExport}>
                    <Download size={14} /> Export bundle
                  </button>
                  {user && project.user_id === user.user_id && (
                    <button className="button secondary small-button edit-project" onClick={() => setShowEditProject(true)}>
                      <Pencil size={14} /> Edit
                    </button>
                  )}
                </div>
              </section>

              <div className="tab-bar" role="tablist" aria-label="Project sections">
                <TabButton active={view === "documents"} onClick={() => setView("documents")} icon={<FileText size={16} />}>Documents</TabButton>
                <TabButton active={view === "papers"} onClick={() => setView("papers")} icon={<Library size={16} />}>Literature</TabButton>
                <TabButton active={view === "notes"} onClick={() => setView("notes")} icon={<BookOpen size={16} />}>Notes</TabButton>
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
                        canComment={project.access_role !== "read"}
                        currentUserId={user?.user_id ?? null}
                        isProjectOwner={project.access_role === "owner"}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="section-heading">
                        <div><h2>Research documents</h2><p>Upload up to 20 files at once. Keep this window open until they are accepted; processing can then continue after you close it.</p></div>
                        {canEditProject && <div className="upload-control">
                          <label className="button primary upload-button">
                            <Upload size={16} /> {uploadingFiles ? "Uploading…" : "Add documents"}
                            <input name="files" type="file" accept=".pdf,.docx,.txt,.md" multiple disabled={uploadingFiles} onChange={(event) => {
                              const files = Array.from(event.currentTarget.files ?? []);
                              if (files.length) void uploadDocuments(files);
                              event.currentTarget.value = "";
                            }} />
                          </label>
                        </div>}
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
                              {canEditProject && item.status === "failed" && (
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
                              {canEditProject && document.processing_status !== "processing" && document.processing_status !== "ready" && (
                                <button className="button secondary small-button" onClick={() => void reprocess(document.document_id)}>
                                  {document.processing_status === "failed" ? "Retry" : "Reprocess"}
                                </button>
                              )}
                              {canEditProject && (
                                <button className="icon-button danger-hover" title="Delete document" onClick={() => void deleteDocument(document.document_id)}>
                                  <Trash2 size={16} />
                                </button>
                              )}
                            </article>
                          ))}
                        </div>
                      )}
                      {processing && <p className="processing-note"><LoaderCircle className="spin" size={15} /> Extracting text and preparing documents…</p>}
                    </>
                  )}
                </section>
              )}

              {view === "notes" && (
                <section className="section-content">
                  <div className="section-heading">
                    <div>
                      <h2>Project notes and highlights</h2>
                      <p>Search saved annotations across documents and papers, then select notes to add as context to a source comparison.</p>
                    </div>
                    <button
                      className="button primary"
                      disabled={!selectedProjectAnnotationCount}
                      onClick={useSelectedAnnotationsInAssistant}
                    >
                      <MessageSquareText size={15} /> Use selected in comparison ({selectedProjectAnnotationCount})
                    </button>
                  </div>
                  <div className="annotation-library-controls">
                    <input
                      type="search"
                      value={annotationQuery}
                      onChange={(event) => setAnnotationQuery(event.target.value)}
                      placeholder="Search notes, highlights, or sources…"
                      aria-label="Search project notes and highlights"
                    />
                    <select
                      value={annotationSourceFilter}
                      onChange={(event) => setAnnotationSourceFilter(event.target.value as AnnotationSourceFilter)}
                      aria-label="Filter notes by source type"
                    >
                      <option value="all">All sources</option>
                      <option value="document">Documents</option>
                      <option value="paper">Papers</option>
                    </select>
                    <select
                      value={annotationSort}
                      onChange={(event) => setAnnotationSort(event.target.value as AnnotationSort)}
                      aria-label="Sort project notes"
                    >
                      <option value="newest">Recently updated</option>
                      <option value="oldest">Least recently updated</option>
                    </select>
                    <button
                      className="button secondary small-button"
                      disabled={!visibleProjectAnnotations.length}
                      onClick={() => setSelectedAnnotationIds((current) => {
                        const next = new Set(current);
                        for (const annotation of visibleProjectAnnotations) {
                          if (allVisibleAnnotationsSelected) next.delete(annotation.annotation_id);
                          else next.add(annotation.annotation_id);
                        }
                        return next;
                      })}
                    >
                      {allVisibleAnnotationsSelected ? "Clear visible selection" : "Select visible"}
                    </button>
                  </div>
                  {visibleProjectAnnotations.length ? (
                    <div className="annotation-library-list">
                      {visibleProjectAnnotations.map((annotation) => (
                        <article className="annotation-library-card" key={annotation.annotation_id}>
                          <label className="annotation-library-select">
                            <input
                              type="checkbox"
                              checked={selectedAnnotationIds.has(annotation.annotation_id)}
                              onChange={(event) => toggleAnnotationSelection(annotation.annotation_id, event.target.checked)}
                              aria-label={`Select note from ${annotation.source_title}`}
                            />
                          </label>
                          <div className="annotation-library-body">
                            <div className="annotation-library-source">
                              <span>{annotation.source_type === "document" ? "DOCUMENT" : "PAPER"}</span>
                              <button type="button" onClick={() => openProjectAnnotation(annotation)}>
                                {annotation.source_title}
                              </button>
                            </div>
                            {annotation.quote && <blockquote>{annotation.quote}</blockquote>}
                            {annotation.note && <p>{annotation.note}</p>}
                            <small>Updated {new Date(annotation.updated_at).toLocaleDateString()}</small>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="annotation-library-empty">
                      <BookOpen size={22} />
                      <p>{projectAnnotations.length
                        ? "No saved notes match these filters."
                        : "No notes or highlights yet. Annotate a document or saved paper to see it here."}</p>
                    </div>
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
                      {canEditProject && <label className="button secondary small-button reference-import-button">
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
                      </label>}
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
                  {savedPaperSearches.length > 0 && (
                    <section className="saved-searches">
                      <div className="result-label"><span>Saved searches</span><small>{savedPaperSearches.length} queries</small></div>
                      {savedPaperSearches.map((saved) => (
                        <article className="saved-search-row" key={saved.saved_search_id}>
                          <div className="saved-search-copy">
                            <strong>{saved.query_text}</strong>
                            <small>{saved.api_provider === "openalex" ? "OpenAlex" : "Crossref"}</small>
                          </div>
                          <label className="saved-search-alert-toggle">
                            <input
                              type="checkbox"
                              checked={saved.alert_enabled}
                              disabled={savedSearchBusy}
                              onChange={(event) => void setSavedSearchAlerts(saved, event.target.checked)}
                            />
                            Alert me
                          </label>
                          <button
                            className="button secondary small-button"
                            disabled={busy}
                            onClick={() => void rerunSavedPaperSearch(saved)}
                          >
                            {busy ? "Searching…" : "Rerun"}
                          </button>
                          <button
                            className="button secondary small-button"
                            disabled={savedSearchBusy}
                            onClick={() => void removeSavedPaperSearch(saved)}
                          >
                            Remove
                          </button>
                        </article>
                      ))}
                    </section>
                  )}
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
                      <div className="save-search-control">
                        <label>
                          <input
                            type="checkbox"
                            checked={saveSearchAlerts}
                            onChange={(event) => setSaveSearchAlerts(event.target.checked)}
                            aria-label="Enable alerts for this saved search"
                          />
                          Alert me when new results match
                        </label>
                        <button
                          className="button secondary small-button"
                          disabled={savedSearchBusy || savedPaperSearches.some((saved) =>
                            saved.query_text === searchResults.query && saved.api_provider === searchResults.provider
                          )}
                          onClick={() => void savePaperSearch(searchResults)}
                        >
                          {savedPaperSearches.some((saved) =>
                            saved.query_text === searchResults.query && saved.api_provider === searchResults.provider
                          ) ? "Search saved" : "Save search"}
                        </button>
                      </div>
                      {searchResults.results.length ? searchResults.results.map((paper) => (
                        <PaperCard
                          key={paper.paper_id}
                          paper={paper}
                          canEditProject={canEditProject}
                          canCommentOnProject={canCommentOnProject}
                          onSave={() => void savePaper(paper)}
                        />
                      )) : <EmptyState icon={<Search size={21} />} title="No results found" text="Try a broader query or use the other search provider." />}
                    </div>
                  )}
                  <section className="systematic-review-card" aria-labelledby="systematic-review-title">
                    <div className="systematic-review-heading">
                      <div>
                        <h3 id="systematic-review-title">Systematic review workspace</h3>
                        <p>Share the review question and protocol with this project’s collaborators.</p>
                      </div>
                      <button
                        className="button secondary small-button"
                        onClick={() => void exportSystematicReview()}
                        disabled={!systematicReview || reviewDirty || referenceBusy}
                        title={reviewDirty ? "Save your review details before exporting." : undefined}
                      >
                        <Download size={14} /> Export review report
                      </button>
                    </div>
                    {reviewLoading && !systematicReview && (
                      <p className="muted compact">Loading the shared review workspace…</p>
                    )}
                    {reviewLoadError && (
                      <div className="systematic-review-error" role="alert">
                        <span>{reviewLoadError}</span>
                        <button
                          className="text-button"
                          onClick={() => setReviewReloadKey((current) => current + 1)}
                        >
                          Retry
                        </button>
                      </div>
                    )}
                    {systematicReview && (
                      <div className="systematic-review-form">
                        <label>
                          Review question
                          <input
                            value={reviewQuestion}
                            onChange={(event) => setReviewQuestion(event.target.value)}
                            maxLength={2_000}
                            placeholder="What question will this review answer?"
                            readOnly={!canEditProject || reviewSaveBusy}
                          />
                        </label>
                        <label>
                          Protocol
                          <textarea
                            value={reviewProtocol}
                            onChange={(event) => setReviewProtocol(event.target.value)}
                            maxLength={20_000}
                            rows={5}
                            placeholder="Record eligibility criteria, screening rules, and other review decisions."
                            readOnly={!canEditProject || reviewSaveBusy}
                          />
                        </label>
                        <div className="systematic-review-footer">
                          <span>
                            {reviewDirty
                              ? "Unsaved changes"
                              : systematicReview.updated_at
                                ? `Saved ${new Date(systematicReview.updated_at).toLocaleString()}`
                                : "No review details saved yet"}
                          </span>
                          <button
                            className="button primary small-button"
                            onClick={() => void saveSystematicReview()}
                            disabled={!canEditProject || reviewLoading || reviewSaveBusy || !reviewDirty}
                          >
                            {reviewSaveBusy ? "Saving…" : "Save review details"}
                          </button>
                        </div>
                        {reviewConflict && (
                          <div className="systematic-review-error" role="alert">
                            <span>This protocol changed in another session. Reload the latest version before saving.</span>
                            <button
                              className="text-button"
                              onClick={() => {
                                setError("");
                                setReviewReloadKey((current) => current + 1);
                              }}
                            >
                              Reload latest
                            </button>
                          </div>
                        )}
                        {reviewDirty && (
                          <p className="muted compact">Save your changes before exporting the review report.</p>
                        )}
                      </div>
                    )}
                  </section>
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
                    {papers.length > 0 && (
                      <div className="screening-workbench">
                        <div className="screening-controls screening-workbench-controls">
                          <label>
                            Filter by decision
                            <select
                              value={screeningFilter}
                              onChange={(event) => setScreeningFilter(event.target.value as ScreeningStatusFilter)}
                            >
                              <option value="all">All decisions</option>
                              <option value="unread">Unread</option>
                              <option value="undecided">Undecided</option>
                              <option value="include">Included</option>
                              <option value="exclude">Excluded</option>
                            </select>
                          </label>
                          <label>
                            Search saved papers
                            <input
                              value={screeningQuery}
                              onChange={(event) => setScreeningQuery(event.target.value)}
                              placeholder="Title, author, abstract, DOI…"
                            />
                          </label>
                          <label>
                            Sort by
                            <select
                              value={screeningSort}
                              onChange={(event) => setScreeningSort(event.target.value as ScreeningSort)}
                            >
                              <option value="saved">Recently saved</option>
                              <option value="title">Title</option>
                              <option value="year_desc">Newest publication year</option>
                              <option value="year_asc">Oldest publication year</option>
                            </select>
                          </label>
                          <button
                            className="button secondary small-button"
                            onClick={toggleVisiblePaperSelection}
                            disabled={!canEditProject || !visibleScreeningPapers.length}
                          >
                            {allVisibleScreeningPapersSelected ? "Deselect visible" : "Select visible"}
                          </button>
                          <button
                            className="button secondary small-button"
                            onClick={() => void exportScreeningCsv()}
                            disabled={referenceBusy || !papers.length}
                          >
                            <Download size={14} /> Export screening CSV
                          </button>
                        </div>
                        {selectedScreeningCount > 0 && (
                          <div className="bulk-screening-actions">
                            <span>{selectedScreeningCount} selected</span>
                            <label>
                              Set decision to
                              <select
                                value={bulkScreeningStatus}
                                onChange={(event) =>
                                  setBulkScreeningStatus(event.target.value as Paper["screening_status"])
                                }
                                disabled={!canEditProject}
                              >
                                <option value="unread">Unread</option>
                                <option value="undecided">Undecided</option>
                                <option value="include">Include</option>
                                <option value="exclude">Exclude</option>
                              </select>
                            </label>
                            <button
                              className="button primary small-button"
                              onClick={() => void bulkUpdatePaperScreening()}
                              disabled={!canEditProject || screeningBusy}
                            >
                              {screeningBusy ? "Applying…" : "Apply to selected"}
                            </button>
                            <button
                              className="button secondary small-button"
                              onClick={() => setSelectedPaperIds(new Set())}
                              disabled={screeningBusy}
                            >
                              Clear selection
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                    {papers.length ? visibleScreeningPapers.map((paper) => (
                      <Fragment key={paper.paper_id}>
                        <PaperCard
                          paper={paper}
                          saved
                          canEditProject={canEditProject}
                          canCommentOnProject={canCommentOnProject}
                          selected={selectedPaperIds.has(paper.paper_id)}
                          onSelectionChange={canEditProject
                            ? (selected) => togglePaperSelection(paper.paper_id, selected)
                            : undefined}
                          onScreeningChange={canEditProject
                            ? (status, note) => void updatePaperScreening(paper, status, note)
                            : undefined}
                          onRemove={canEditProject ? () => void unsavePaper(paper) : undefined}
                          onAnnotate={() => setAnnotationPaperId((current) => current === paper.paper_id ? null : paper.paper_id)}
                          onImportFullText={canEditProject ? () => void importPaperFullText(paper) : undefined}
                          importingFullText={busy}
                        />
                        {annotationPaperId === paper.paper_id && (
                          <AnnotationEditor
                            key={`annotations-${paper.paper_id}`}
                            annotationsPath={`/api/projects/${project.project_id}/papers/${paper.paper_id}/annotations`}
                            sourceText={paper.abstract?.replace(/<[^>]*>/g, "") ?? ""}
                            canComment={project.access_role !== "read"}
                            currentUserId={user?.user_id ?? null}
                            isProjectOwner={project.access_role === "owner"}
                          />
                        )}
                      </Fragment>
                    )) : <p className="muted compact">Your saved papers will appear here.</p>}
                    {papers.length > 0 && visibleScreeningPapers.length === 0 && (
                      <p className="muted compact">No saved papers match these screening filters.</p>
                    )}
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
                              <div className="message-footer">
                                <span className="approved-label"><ShieldCheck size={13} /> Human-reviewed</span>
                                {message.sources.length > 0 && isEvidenceComparison(message.content) && (
                                  <button
                                    className="brief-export-button"
                                    disabled={briefExportingMessageId !== null}
                                    onClick={() => void exportResearchBrief(message)}
                                  >
                                    {briefExportingMessageId === message.message_id
                                      ? <LoaderCircle className="spin" size={13} />
                                      : <Download size={13} />}
                                    Export cited brief
                                  </button>
                                )}
                              </div>
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
                        <button
                          className="button primary send-button"
                          disabled={busy || question.trim().length < 3 || aiUsage?.assistant_prompts_remaining === 0}
                        >
                          {busy ? <LoaderCircle className="spin" size={16} /> : <Send size={15} />}
                          {aiUsage?.assistant_prompts_remaining === 0 ? "Limit reached" : "Generate"}
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

type AccountSettingsDialogProps = {
  user: User;
  aiUsage: AIUsageResponse | null;
  processingStatusCounts: {
    processing: number;
    failed: number;
    quotaExceeded: number;
    needsApiKey: number;
  };
  request: <T,>(path: string, options?: RequestInit) => Promise<T>;
  onUserUpdated: (user: User) => void;
  onClose: () => void;
};

function AccountSettingsDialog({
  user,
  aiUsage,
  processingStatusCounts,
  request,
  onUserUpdated,
  onClose,
}: AccountSettingsDialogProps) {
  const [name, setName] = useState(user.name);
  const [username, setUsername] = useState(user.username ?? "");
  const [profilePicture, setProfilePicture] = useState(user.profile_picture);
  const [settingsPage, setSettingsPage] = useState<"profile" | "ai-usage">("profile");
  const [showPasswordEditor, setShowPasswordEditor] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await request<User>("/api/auth/profile", {
        method: "PATCH",
        body: jsonBody({ name, username, profile_picture: profilePicture }),
      });
      onUserUpdated(updated);
      setName(updated.name);
      setUsername(updated.username ?? "");
      setProfilePicture(updated.profile_picture);
      setNotice("Profile settings saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your profile.");
    } finally {
      setBusy(false);
    }
  }

  async function updateProfilePicture(file: File | undefined) {
    if (!file) return;
    setError("");
    try {
      setProfilePicture(await createProfilePicture(file));
      setNotice("Profile picture ready. Save profile settings to apply it.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load this image.");
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setBusy(true);
    setError("");
    setNotice("");
    const form = new FormData(formElement);
    try {
      await request<{ message: string }>("/api/auth/password", {
        method: "POST",
        body: jsonBody({
          current_password: form.get("current_password"),
          new_password: form.get("new_password"),
        }),
      });
      formElement.reset();
      setShowPasswordEditor(false);
      setNotice("Password changed successfully.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not change your password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card settings-modal" role="dialog" aria-modal="true" aria-labelledby="account-settings-title">
        <div className="modal-heading">
          <div>
            <p className="eyebrow">YOUR ACCOUNT</p>
            <h2 id="account-settings-title">Profile & settings</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close settings">
            <X size={18} />
          </button>
        </div>
        {error && <Notice kind="error" text={error} />}
        {notice && <Notice kind="success" text={notice} />}
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="Settings pages">
            <button
              className={settingsPage === "profile" ? "active" : ""}
              type="button"
              aria-current={settingsPage === "profile" ? "page" : undefined}
              onClick={() => setSettingsPage("profile")}
            >
              Profile
            </button>
            <button
              className={settingsPage === "ai-usage" ? "active" : ""}
              type="button"
              aria-current={settingsPage === "ai-usage" ? "page" : undefined}
              onClick={() => setSettingsPage("ai-usage")}
            >
              AI usage
            </button>
          </nav>
          <div className="settings-page">
        {settingsPage === "profile" ? (
          <>
        <form className="stack-form settings-profile-form" onSubmit={(event) => void saveProfile(event)}>
          <div className="settings-section-heading">
            <h3>Profile</h3>
            <p>Update how you appear in Fieldnotes.</p>
          </div>
          <div className="profile-picture-control">
            <span className="avatar profile-picture-preview">
              {profilePicture
                ? <img src={profilePicture} alt="Profile preview" />
                : name.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <label className="button secondary small-button profile-picture-upload">
                Choose picture
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(event) => {
                    void updateProfilePicture(event.currentTarget.files?.[0]);
                    event.currentTarget.value = "";
                  }}
                />
              </label>
              {profilePicture && (
                <button
                  className="text-button profile-picture-remove"
                  type="button"
                  onClick={() => setProfilePicture(null)}
                >
                  Remove picture
                </button>
              )}
              <small>JPEG, PNG, or WebP. Images are cropped and resized before upload.</small>
            </div>
          </div>
          <label>
            Email
            <input value={user.email} readOnly />
            <span className="field-note">Your sign-in email cannot be changed here.</span>
          </label>
          <label>
            Username
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              minLength={3}
              maxLength={32}
              pattern="([A-Za-z0-9._]|-)+"
              autoComplete="username"
            />
          </label>
          <label>
            Display name
            <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} />
          </label>
          <button className="button primary" disabled={busy}>
            {busy ? "Saving…" : "Save profile"}
          </button>
        </form>

        <section className="settings-password">
          <div className="settings-section-heading">
            <h3>Password</h3>
            <p>Passwords are securely hashed and cannot be viewed. You can change yours below.</p>
          </div>
          {!showPasswordEditor ? (
            <button
              className="button secondary small-button"
              type="button"
              onClick={() => {
                setError("");
                setNotice("");
                setShowPasswordEditor(true);
              }}
            >
              Change password
            </button>
          ) : (
            <form className="stack-form" onSubmit={(event) => void changePassword(event)}>
              <label>
                Current password
                <span className="password-input-wrap">
                  <input name="current_password" type={showCurrentPassword ? "text" : "password"} required autoComplete="current-password" />
                  <button
                    className="password-toggle"
                    type="button"
                    aria-label={showCurrentPassword ? "Hide current password" : "Show current password"}
                    onClick={() => setShowCurrentPassword((visible) => !visible)}
                  >
                    {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
              <label>
                New password <span className="field-note">12+ characters; avoid common passwords</span>
                <span className="password-input-wrap">
                  <input name="new_password" type={showNewPassword ? "text" : "password"} required minLength={12} maxLength={128} autoComplete="new-password" />
                  <button
                    className="password-toggle"
                    type="button"
                    aria-label={showNewPassword ? "Hide new password" : "Show new password"}
                    onClick={() => setShowNewPassword((visible) => !visible)}
                  >
                    {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
              <div className="settings-actions">
                <button className="button primary small-button" disabled={busy}>{busy ? "Updating…" : "Update password"}</button>
                <button className="button secondary small-button" type="button" onClick={() => setShowPasswordEditor(false)}>Cancel</button>
              </div>
            </form>
          )}
        </section>
          </>
        ) : (
        <section className="settings-usage">
          <div className="settings-section-heading">
            <h3>AI usage</h3>
            <p>Daily allowances reset at 00:00 UTC.</p>
          </div>
          <div className="ai-usage-panel settings-usage-panel" aria-label="Daily AI allowance and processing status">
            {aiUsage ? (
              <div className="ai-usage-metrics">
                <UsageMeter
                  label="Assistant prompts"
                  detail="Shared by IP address"
                  used={aiUsage.assistant_prompts_used}
                  limit={aiUsage.assistant_prompts_limit}
                  remaining={`${aiUsage.assistant_prompts_remaining.toLocaleString()} remaining`}
                />
                <UsageMeter
                  label="Embedding tokens"
                  detail="Estimated · per account"
                  used={aiUsage.embedding_tokens_used}
                  limit={aiUsage.embedding_tokens_limit}
                  remaining={`${aiUsage.embedding_tokens_remaining.toLocaleString()} remaining`}
                />
              </div>
            ) : (
              <p className="ai-usage-unavailable">Daily AI allowance is unavailable.</p>
            )}
            <div className="processing-summary" aria-live="polite">
              <strong>Document processing</strong>
              <span>{processingStatusCounts.processing} processing</span>
              <span>{processingStatusCounts.failed} failed</span>
              <span>{processingStatusCounts.quotaExceeded} at AI allowance limit</span>
              <span>{processingStatusCounts.needsApiKey} waiting for API key</span>
            </div>
            <p className="ai-usage-note">
              Embedding usage includes uploads, open-access imports, and reprocessing.
            </p>
          </div>
        </section>
        )}
          </div>
        </div>
      </section>
    </div>
  );
}

async function createProfilePicture(file: File): Promise<string> {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    throw new Error("Choose a JPEG, PNG, or WebP image.");
  }
  if (file.size > 10 * 1024 * 1024) {
    throw new Error("Choose an image smaller than 10 MB.");
  }
  const image = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 256;
  const context = canvas.getContext("2d");
  if (!context) {
    image.close();
    throw new Error("Your browser could not process this image.");
  }
  const scale = Math.max(256 / image.width, 256 / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  context.drawImage(image, (256 - width) / 2, (256 - height) / 2, width, height);
  image.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
  if (!blob || blob.size > 512 * 1024) {
    throw new Error("Could not resize the image to the supported size.");
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === "string"
      ? resolve(reader.result)
      : reject(new Error("Could not read the resized image."));
    reader.onerror = () => reject(new Error("Could not read the resized image."));
    reader.readAsDataURL(blob);
  });
}

function UsageMeter({
  label,
  detail,
  used,
  limit,
  remaining,
}: {
  label: string;
  detail: string;
  used: number;
  limit: number;
  remaining: string;
}) {
  const percentage = Math.min(100, Math.max(0, (used / limit) * 100));
  return (
    <div className="ai-usage-meter">
      <div className="ai-usage-meter-label">
        <span><strong>{label}</strong><small>{detail}</small></span>
        <b>{remaining}</b>
      </div>
      <div
        className="ai-usage-track"
        role="progressbar"
        aria-label={`${label} used`}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={Math.min(used, limit)}
      >
        <span style={{ width: `${percentage}%` }} />
      </div>
      <small>{used.toLocaleString()} of {limit.toLocaleString()} used</small>
    </div>
  );
}

function isEvidenceComparison(content: string): boolean {
  return /^\|\s*Source\s*\|\s*Research question\s*\|\s*Methods\s*\|\s*Sampling\s*\|\s*Findings\s*\|\s*Limitations\s*\|\s*Citations\s*\|$/m.test(content);
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
    quota_exceeded: "AI allowance reached",
  };
  const label = labels[status] ?? status;
  return (
    <span className={`status-pill status-${status}`} aria-label={label} title={label}>
      {["uploading", "processing"].includes(status) && <LoaderCircle size={12} className="spin" />}
      {status === "quota_exceeded" && <AlertCircle size={12} />}
      {label}
    </span>
  );
}

function PaperCard({
  paper,
  saved = false,
  canEditProject,
  canCommentOnProject,
  onSave,
  onRemove,
  onAnnotate,
  onScreeningChange,
  selected = false,
  onSelectionChange,
  onImportFullText,
  importingFullText,
}: {
  paper: Paper;
  saved?: boolean;
  canEditProject: boolean;
  canCommentOnProject: boolean;
  onSave?: () => void;
  onRemove?: () => void;
  onAnnotate?: () => void;
  onScreeningChange?: (status: Paper["screening_status"], note: string) => void;
  selected?: boolean;
  onSelectionChange?: (selected: boolean) => void;
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
      {onSelectionChange && (
        <label className="paper-select">
          <input
            type="checkbox"
            checked={selected}
            onChange={(event) => onSelectionChange(event.target.checked)}
            aria-label={`Select ${paper.title} for bulk screening`}
          />
        </label>
      )}
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
                disabled={!canEditProject}
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
                disabled={!canEditProject}
              />
            </label>
            <button
              className="button secondary small-button"
              onClick={() => onScreeningChange?.(screeningStatus, screeningNote)}
              disabled={!onScreeningChange ||
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
            <button className="button secondary small-button" onClick={onAnnotate} disabled={!canCommentOnProject}><Pencil size={13} /> Comment</button>
            <button className="button secondary small-button" onClick={onImportFullText} disabled={!canEditProject || importingFullText}>
              {importingFullText ? <LoaderCircle size={13} className="spin" /> : <FileText size={13} />}
              {importingFullText ? "Importing…" : "Extract full text"}
            </button>
            {onRemove && <button className="button secondary small-button" onClick={onRemove}><X size={14} /> Remove</button>}
          </>
        ) : (
          <button className="button secondary small-button" onClick={onSave} disabled={!canEditProject}><Plus size={15} /> Save</button>
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
  canComment,
  currentUserId,
  isProjectOwner,
}: {
  annotationsPath: string;
  sourcePath?: string;
  sourceText?: string;
  sourceStatus?: string;
  canComment: boolean;
  currentUserId: string | null;
  isProjectOwner: boolean;
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

  useEffect(() => {
    if (busy || editingId) return;
    let active = true;
    const timer = window.setInterval(() => {
      api<Annotation[]>(annotationsPath)
        .then((loadedAnnotations) => {
          if (active) setAnnotations(loadedAnnotations);
        })
        .catch((cause: unknown) => {
          if (active) setError(cause instanceof Error ? cause.message : "Could not sync shared annotations.");
        });
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [annotationsPath, busy, editingId]);

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
        <div><h3>Source comments</h3><p>Select text to highlight it, or add a comment on its own.</p></div>
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
          {canComment && text && (
            <div className="annotation-selection">
              <button className="button secondary small-button" type="button" onMouseDown={(event) => event.preventDefault()} onClick={captureSelection}>Highlight selection</button>
              {selection && <span>Selected: “{selection.quote.slice(0, 180)}{selection.quote.length > 180 ? "…" : ""}”</span>}
            </div>
          )}
          {canComment && <form className="annotation-form" onSubmit={(event) => void saveAnnotation(event)}>
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
              {busy ? "Saving…" : "Add comment"}
            </button>
          </form>}
          {!!annotations.length && (
            <div className="annotation-list">
              {annotations.map((item) => (
                <article className="annotation-item" key={item.annotation_id}>
                  {item.quote && <blockquote>{item.quote}</blockquote>}
                  <small className="annotation-author">{item.author_name ?? "Original project note"}</small>
                  {editingId === item.annotation_id ? (
                    <div className="annotation-edit">
                      <textarea value={editNote} onChange={(event) => setEditNote(event.target.value)} maxLength={5000} rows={2} />
                      <button className="button secondary small-button" type="button" disabled={busy} onClick={() => void updateAnnotation(item)}>Save note</button>
                      <button className="text-button" type="button" onClick={() => setEditingId(null)}>Cancel</button>
                    </div>
                  ) : (
                    <>
                      {item.note && <p>{item.note}</p>}
                      {(isProjectOwner || item.author_id === currentUserId) && (
                        <div className="annotation-actions">
                          <button className="text-button" type="button" onClick={() => { setEditingId(item.annotation_id); setEditNote(item.note); }}>Edit comment</button>
                          <button className="text-button danger-text" type="button" disabled={busy} onClick={() => void deleteAnnotation(item)}>Delete</button>
                        </div>
                      )}
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
