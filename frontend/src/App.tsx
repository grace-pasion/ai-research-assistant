import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Bell,
  Bot,
  Check,
  Download,
  Eye,
  EyeOff,
  FileText,
  FileCode2,
  FolderPlus,
  Library,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Menu,
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
import { Fragment, type FormEvent, type ReactNode, type TextareaHTMLAttributes, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, downloadFile, fetchPdfObjectUrl, getToken, jsonBody, setToken } from "./api";
import { allAssistantSources, withoutAssistantSource, type AssistantSourceSelection } from "./assistantSources";
import { findCitationRange } from "./citationEvidence";
import {
  resolveGlobalShortcut,
  type ProjectSectionView,
} from "./globalShortcuts";
import { getMentionQuery, insertMention } from "./mentions";
import { CrossProjectSearch } from "./CrossProjectSearch";
import { ProjectCollections } from "./ProjectCollections";
import { ProjectHome } from "./ProjectHome.tsx";
import { WorkStatusPanel } from "./WorkStatusPanel";
import {
  buildWorkStatusItems,
  type LatexCompileActivity,
  type WorkStatusUpload,
} from "./workStatus";
import { StudyExtractionTable } from "./StudyExtractionTable";
import { addRecentProjectSource, parseRecentProjectSources } from "./projectHome";
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
  hasScreeningDisagreement,
  SCREENING_EXCLUSION_REASONS,
  type ScreeningSort,
  type ScreeningStatusFilter,
} from "./literatureScreening";
import { summarizeScreeningAssignments } from "./screeningAssignments";
import {
  filterProjectAnnotations,
  formatSelectedAnnotations,
  type AnnotationSort,
  type AnnotationSourceFilter,
} from "./projectAnnotations";
import {
  filterByLibraryMetadata,
  type LibraryMetadataFilters,
} from "./libraryMetadata";
import { literatureSearchRequest } from "./searchHistory";
import {
  findPaperSimilarityMatches,
  type PaperSimilarityMatch,
} from "./paperSimilarity";
import type { StudyExtractionValues } from "./studyExtraction";
import type {
  AIUsageResponse,
  Annotation,
  AnnotationSourceLink,
  BulkDocumentUploadResponse,
  Conversation,
  CrossProjectSearchResult,
  DocumentRecord,
  DocumentSearchResult,
  Draft,
  Message,
  PaperImportResponse,
  Paper,
  PaperScreeningAssignment,
  PaperStudyExtraction,
  PaperScreeningDecision,
  ProjectAnnotation,
  Project,
  ProjectCollaborator,
  ProjectTask,
  RecentProjectSource,
  ResearchPacketAssistantOutputOption,
  ScreeningExclusionReason,
  SavedPaperSearch,
  SavedPaperSearchRun,
  SearchQueryHistoryRecord,
  SearchResult,
  Source,
  SourceSummaryResponse,
  SystematicReview,
  TeamWorkspace,
  User,
} from "./types";

type View = ProjectSectionView | "search";
type LoginResponse = { access_token: string; user: User };
const MAX_BULK_UPLOAD_COUNT = 20;
type UploadQueueItem = {
  key: string;
  projectId: string;
  file: File;
  filename: string;
  status: WorkStatusUpload["status"];
  documentId: string | null;
  error: string | null;
};
type ProjectAnnotationUpdate = Partial<
  Pick<Annotation, "note" | "tags" | "is_pinned" | "related_sources">
>;
type PendingPaperSave = {
  projectId: string;
  paper: Paper;
  matches: PaperSimilarityMatch[];
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
  const [view, setView] = useState<View>("home");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [aiUsage, setAiUsage] = useState<AIUsageResponse | null>(null);
  const [bulkUploads, setBulkUploads] = useState<UploadQueueItem[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [latexCompileActivities, setLatexCompileActivities] = useState<
    Record<string, LatexCompileActivity>
  >({});
  const [annotationDocumentId, setAnnotationDocumentId] = useState<string | null>(null);
  const [citationPage, setCitationPage] = useState<number | null>(null);
  const [citationExcerpt, setCitationExcerpt] = useState<string | null>(null);
  const [annotationPaperId, setAnnotationPaperId] = useState<string | null>(null);
  const [showQuickNote, setShowQuickNote] = useState(false);
  const [quickNoteSourceSelection, setQuickNoteSourceSelection] = useState("");
  const [quickNoteText, setQuickNoteText] = useState("");
  const [quickNoteBusy, setQuickNoteBusy] = useState(false);
  const [quickNoteError, setQuickNoteError] = useState("");
  const [projectAnnotations, setProjectAnnotations] = useState<ProjectAnnotation[]>([]);
  const [projectCollaborators, setProjectCollaborators] = useState<ProjectCollaborator[]>([]);
  const [projectTasks, setProjectTasks] = useState<ProjectTask[]>([]);
  const [recentSources, setRecentSources] = useState<{
    userId: string;
    projectId: string;
    sources: RecentProjectSource[];
  }>({ userId: "", projectId: "", sources: [] });
  const [recentSourcesError, setRecentSourcesError] = useState<{
    userId: string;
    projectId: string;
    message: string;
  }>({ userId: "", projectId: "", message: "" });
  const [taskSourceSelection, setTaskSourceSelection] = useState("");
  const [taskAnnotationSelection, setTaskAnnotationSelection] = useState("");
  const [taskAssigneeSelection, setTaskAssigneeSelection] = useState("");
  const [taskBusyId, setTaskBusyId] = useState<string | null>(null);
  const [taskSaving, setTaskSaving] = useState(false);
  const [annotationQuery, setAnnotationQuery] = useState("");
  const [annotationSourceFilter, setAnnotationSourceFilter] = useState<AnnotationSourceFilter>("all");
  const [annotationSort, setAnnotationSort] = useState<AnnotationSort>("newest");
  const [pinnedAnnotationsOnly, setPinnedAnnotationsOnly] = useState(false);
  const [selectedAnnotationIds, setSelectedAnnotationIds] = useState<Set<string>>(() => new Set());
  const [annotationBusyIds, setAnnotationBusyIds] = useState<Set<string>>(() => new Set());
  const [documentQuery, setDocumentQuery] = useState("");
  const [documentMatches, setDocumentMatches] = useState<DocumentSearchResult[] | null>(null);
  const [documentMetadataFilters, setDocumentMetadataFilters] = useState<LibraryMetadataFilters>({
    tag: "",
    metadataKey: "",
    metadataValue: "",
  });
  const [paperMetadataFilters, setPaperMetadataFilters] = useState<LibraryMetadataFilters>({
    tag: "",
    metadataKey: "",
    metadataValue: "",
  });
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
  const [bulkExclusionReason, setBulkExclusionReason] =
    useState<ScreeningExclusionReason | "">("");
  const [bulkScreeningNote, setBulkScreeningNote] = useState("");
  const [screeningBusy, setScreeningBusy] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [pendingPaperSave, setPendingPaperSave] = useState<PendingPaperSave | null>(null);
  const [searchHistory, setSearchHistory] = useState<SearchQueryHistoryRecord[]>([]);
  const [savedPaperSearches, setSavedPaperSearches] = useState<SavedPaperSearch[]>([]);
  const [saveSearchAlerts, setSaveSearchAlerts] = useState(false);
  const [savedSearchBusy, setSavedSearchBusy] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftQuestion, setDraftQuestion] = useState("");
  const [assistantSources, setAssistantSources] = useState<AssistantSourceSelection | null>(null);
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
  const [showResearchPacket, setShowResearchPacket] = useState(false);
  const [researchPacketLoading, setResearchPacketLoading] = useState(false);
  const [researchPacketBusy, setResearchPacketBusy] = useState(false);
  const [researchPacketError, setResearchPacketError] = useState("");
  const [researchPacketPapers, setResearchPacketPapers] = useState<Paper[]>([]);
  const [researchPacketNotes, setResearchPacketNotes] = useState<ProjectAnnotation[]>([]);
  const [researchPacketOutputs, setResearchPacketOutputs] =
    useState<ResearchPacketAssistantOutputOption[]>([]);
  const [selectedResearchPacketPaperIds, setSelectedResearchPacketPaperIds] =
    useState<Set<string>>(() => new Set());
  const [selectedResearchPacketNoteIds, setSelectedResearchPacketNoteIds] =
    useState<Set<string>>(() => new Set());
  const [selectedResearchPacketOutputIds, setSelectedResearchPacketOutputIds] =
    useState<Set<string>>(() => new Set());
  const [showInbox, setShowInbox] = useState(false);
  const [showTeamWorkspaces, setShowTeamWorkspaces] = useState(false);
  const [showTeamChannels, setShowTeamChannels] = useState(false);
  const [showAccountSettings, setShowAccountSettings] = useState(false);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [searchText, setSearchText] = useState("");
  const [provider, setProvider] = useState("openalex");
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [briefExportingMessageId, setBriefExportingMessageId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [askMode, setAskMode] = useState<"question" | "compare" | "directions">("question");
  const selectedProjectIdRef = useRef<string | null>(null);
  const sourceSummaryRequestIdRef = useRef(0);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const quickNoteTextRef = useRef<HTMLTextAreaElement | null>(null);
  const [sourceSummary, setSourceSummary] = useState<{
    title: string;
    summary: string | null;
    cached: boolean;
    loading: boolean;
    error: string;
  } | null>(null);
  const canEditProject = project?.access_role === "owner" || project?.access_role === "edit";
  const canCommentOnProject = canEditProject || project?.access_role === "comment";

  useEffect(() => {
    if (!mobileNavigationOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavigationOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavigationOpen]);

  useEffect(() => {
    setSelectedPaperIds(new Set());
    setSelectedAnnotationIds(new Set());
  }, [project?.project_id]);

  const request = useCallback(
    async <T,>(path: string, options?: RequestInit) => api<T>(path, options, token),
    [token],
  );

  useEffect(() => {
    if (!user || !project) {
      setRecentSources({ userId: "", projectId: "", sources: [] });
      setRecentSourcesError({ userId: "", projectId: "", message: "" });
      return;
    }
    const userId = user.user_id;
    const projectId = project.project_id;
    setRecentSourcesError({ userId, projectId, message: "" });
    try {
      const key = `fieldnotes:recent-sources:${userId}:${projectId}`;
      setRecentSources({
        userId,
        projectId,
        sources: parseRecentProjectSources(window.localStorage.getItem(key)),
      });
    } catch {
      setRecentSources({ userId, projectId, sources: [] });
      setRecentSourcesError({
        userId,
        projectId,
        message: "Could not load recently opened sources from this browser.",
      });
    }
  }, [project?.project_id, user?.user_id]);

  function rememberRecentProjectSource(
    projectId: string | null | undefined,
    sourceType: "document" | "paper",
    sourceId: string,
    sourceTitle: string,
  ) {
    if (!user || !projectId) return;
    try {
      const key = `fieldnotes:recent-sources:${user.user_id}:${projectId}`;
      const current = parseRecentProjectSources(window.localStorage.getItem(key));
      const updated = addRecentProjectSource(current, {
        source_type: sourceType,
        source_id: sourceId,
        source_title: sourceTitle,
        opened_at: new Date().toISOString(),
      });
      window.localStorage.setItem(key, JSON.stringify(updated));
      if (projectId === project?.project_id) {
        setRecentSources({ userId: user.user_id, projectId, sources: updated });
        setRecentSourcesError({ userId: user.user_id, projectId, message: "" });
      }
    } catch {
      if (projectId === project?.project_id) {
        setRecentSourcesError({
          userId: user.user_id,
          projectId,
          message: "Could not save recently opened sources in this browser.",
        });
      }
    }
  }

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
    sourceSummaryRequestIdRef.current += 1;
    setSourceSummary(null);
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
    setShowResearchPacket(false);
    setResearchPacketLoading(false);
    setResearchPacketBusy(false);
    setResearchPacketError("");
    setShowQuickNote(false);
    setQuickNoteSourceSelection("");
    setQuickNoteText("");
    setQuickNoteBusy(false);
    setQuickNoteError("");
    setResearchPacketPapers([]);
    setResearchPacketNotes([]);
    setResearchPacketOutputs([]);
    setSelectedResearchPacketPaperIds(new Set());
    setSelectedResearchPacketNoteIds(new Set());
    setSelectedResearchPacketOutputIds(new Set());
    setProjectAnnotations([]);
    setProjectCollaborators([]);
    setProjectTasks([]);
    setTaskSourceSelection("");
    setTaskAnnotationSelection("");
    setTaskAssigneeSelection("");
    setSavedPaperSearches([]);
    setSearchHistory([]);
    setSearchResults(null);
    setConversations([]);
    setAiUsage(null);
    setAssistantSources(null);
    setDraft(null);
    setConversation(null);
  }, [project?.project_id, token]);

  useEffect(() => {
    if (!project || !token || view !== "notes") return;
    let active = true;
    const loadNotesWorkspace = () => {
      Promise.all([
        request<ProjectAnnotation[]>(`/api/projects/${project.project_id}/annotations`),
        request<ProjectTask[]>(`/api/projects/${project.project_id}/tasks`),
        request<ProjectCollaborator[]>(`/api/projects/${project.project_id}/collaborators`),
      ])
        .then(([loadedAnnotations, loadedTasks, loadedCollaborators]) => {
          if (!active) return;
          setProjectAnnotations(loadedAnnotations);
          setProjectTasks(loadedTasks);
          setProjectCollaborators(loadedCollaborators);
        })
        .catch((cause: unknown) => {
          if (active) setError(cause instanceof Error ? cause.message : "Could not load project notes and tasks.");
        });
    };
    loadNotesWorkspace();
    const timer = window.setInterval(loadNotesWorkspace, 30_000);
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
      setSearchHistory([]);
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
    if (!project || !token || view !== "papers") return;
    let active = true;
    request<ProjectCollaborator[]>(`/api/projects/${project.project_id}/collaborators`)
      .then((loaded) => {
        if (active) setProjectCollaborators(loaded);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error
            ? cause.message
            : "Could not load reviewers for paper assignments.");
        }
      });
    return () => {
      active = false;
    };
  }, [project?.project_id, request, token, view]);

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
    request<SearchQueryHistoryRecord[]>(
      `/api/projects/${project.project_id}/papers/search-history?limit=20`,
    )
      .then((history) => {
        if (active) setSearchHistory(history);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load search history.");
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
  const workStatusItems = useMemo(
    () => project
      ? buildWorkStatusItems(
        project.project_id,
        bulkUploads,
        documents,
        latexCompileActivities[project.project_id] ?? null,
      )
      : [],
    [bulkUploads, documents, latexCompileActivities, project?.project_id],
  );
  const reportLatexCompileActivity = useCallback((activity: LatexCompileActivity) => {
    if (!project) return;
    setLatexCompileActivities((current) => ({
      ...current,
      [project.project_id]: activity,
    }));
  }, [project]);
  const screeningCounts = useMemo(() => ({
    unread: papers.filter((paper) => paper.screening_status === "unread").length,
    undecided: papers.filter((paper) => paper.screening_status === "undecided").length,
    include: papers.filter((paper) => paper.screening_status === "include").length,
    exclude: papers.filter((paper) => paper.screening_status === "exclude").length,
  }), [papers]);
  const reviewedPaperCount = screeningCounts.undecided + screeningCounts.include + screeningCounts.exclude;
  const reviewerAssessmentCount = papers.reduce(
    (count, paper) => count + paper.screening_decisions.length,
    0,
  );
  const screeningAssignmentProgress = useMemo(
    () => summarizeScreeningAssignments(papers, projectCollaborators),
    [papers, projectCollaborators],
  );
  const unassignedScreeningPaperCount = papers.filter(
    (paper) => paper.screening_assignments.length === 0,
  ).length;
  const screeningDisagreementCount = papers.filter(
    (paper) => paper.screening_disagreement,
  ).length;
  const visibleDocuments = useMemo(
    () => filterByLibraryMetadata(documents, documentMetadataFilters),
    [documents, documentMetadataFilters],
  );
  const reviewDirty = systematicReview !== null && (
    reviewQuestion !== systematicReview.review_question
    || reviewProtocol !== systematicReview.protocol
  );
  const visibleScreeningPapers = useMemo(
    () => filterByLibraryMetadata(
      filterAndSortScreeningPapers(papers, screeningFilter, screeningQuery, screeningSort),
      paperMetadataFilters,
    ),
    [papers, screeningFilter, screeningQuery, screeningSort, paperMetadataFilters],
  );
  const selectedScreeningCount = papers.filter((paper) => selectedPaperIds.has(paper.paper_id)).length;
  const visibleProjectAnnotations = useMemo(
    () => filterProjectAnnotations(
      projectAnnotations,
      annotationQuery,
      annotationSourceFilter,
      annotationSort,
      pinnedAnnotationsOnly,
    ),
    [annotationQuery, annotationSourceFilter, annotationSort, pinnedAnnotationsOnly, projectAnnotations],
  );
  const projectTaskSources = useMemo(() => [
    ...documents.map((document) => ({
      source_type: "document" as const,
      source_id: document.document_id,
      source_title: document.filename,
    })),
    ...papers.map((paper) => ({
      source_type: "paper" as const,
      source_id: paper.paper_id,
      source_title: paper.title,
    })),
  ], [documents, papers]);
  const resolvedTaskSourceSelection = projectTaskSources.some(
    (source) => `${source.source_type}.${source.source_id}` === taskSourceSelection,
  )
    ? taskSourceSelection
    : projectTaskSources[0]
      ? `${projectTaskSources[0].source_type}.${projectTaskSources[0].source_id}`
      : "";
  const selectedTaskSource = projectTaskSources.find(
    (source) => `${source.source_type}.${source.source_id}` === resolvedTaskSourceSelection,
  );
  const taskAnnotationOptions = selectedTaskSource
    ? projectAnnotations.filter((annotation) =>
      annotation.source_type === selectedTaskSource.source_type
      && (annotation.source_type === "document"
        ? annotation.document_id === selectedTaskSource.source_id
        : annotation.paper_id === selectedTaskSource.source_id),
    )
    : [];
  const resolvedTaskAssigneeSelection = projectCollaborators.some(
    (collaborator) => collaborator.user_id === taskAssigneeSelection,
  )
    ? taskAssigneeSelection
    : projectCollaborators.find((collaborator) => collaborator.user_id === user?.user_id)?.user_id
      ?? projectCollaborators[0]?.user_id
      ?? "";
  const selectedProjectAnnotationCount = projectAnnotations
    .filter((annotation) => selectedAnnotationIds.has(annotation.annotation_id)).length;
  const allVisibleAnnotationsSelected = visibleProjectAnnotations.length > 0
    && visibleProjectAnnotations.every((annotation) => selectedAnnotationIds.has(annotation.annotation_id));
  const allVisibleScreeningPapersSelected = visibleScreeningPapers.length > 0
    && visibleScreeningPapers.every((paper) => selectedPaperIds.has(paper.paper_id));
  const openedDocument = annotationDocumentId
    ? documents.find((document) => document.document_id === annotationDocumentId) ?? null
    : null;

  useEffect(() => {
    if (!token || !user) return;
    const handleGlobalShortcut = (event: KeyboardEvent) => {
      const target = event.target;
      const editingText = target instanceof HTMLElement
        && (target.isContentEditable || target.matches("input, textarea, select, [role='textbox']"));
      const dialogOpen = Boolean(document.querySelector('[role="dialog"], [aria-modal="true"]'));
      const action = resolveGlobalShortcut(event, editingText || dialogOpen);
      if (!action) return;

      event.preventDefault();
      if (action.type === "search") {
        setView("search");
        setMobileNavigationOpen(false);
        return;
      }
      if (action.type === "section") {
        if (!project) return;
        setView(action.view);
        setMobileNavigationOpen(false);
        return;
      }
      if (!project) {
        setError("Select a project before creating a note or uploading documents.");
        return;
      }
      if (action.type === "new-note") {
        if (!canCommentOnProject) {
          setError("Comment access is required to create a note.");
          return;
        }
        openQuickNote();
        return;
      }
      if (!canEditProject) {
        setError("Editor access is required to upload documents.");
        return;
      }
      if (uploadingFiles) {
        setError("Wait for the current upload to finish before starting another.");
        return;
      }
      setView("documents");
      uploadInputRef.current?.click();
    };
    window.addEventListener("keydown", handleGlobalShortcut);
    return () => window.removeEventListener("keydown", handleGlobalShortcut);
  }, [
    canCommentOnProject,
    canEditProject,
    project,
    projectTaskSources,
    token,
    uploadingFiles,
    user,
  ]);

  function openDocumentEvidence(
    documentId: string,
    pageNumber: number | null = null,
    excerpt: string | null = null,
    sourceProjectId: string | null | undefined = project?.project_id,
    sourceTitle?: string,
  ) {
    const title = sourceTitle ?? documents.find(
      (document) => document.document_id === documentId,
    )?.filename;
    if (title) {
      rememberRecentProjectSource(sourceProjectId, "document", documentId, title);
    }
    setAnnotationDocumentId(documentId);
    setCitationPage(pageNumber);
    setCitationExcerpt(excerpt);
    setView("documents");
  }

  function openProjectSource(sourceType: "document" | "paper", sourceId: string, sourceTitle: string) {
    if (sourceType === "document") {
      if (!documents.some((document) => document.document_id === sourceId)) {
        setError("This linked document is no longer available in the project.");
        return;
      }
      openDocumentEvidence(sourceId);
      return;
    }
    if (!papers.some((paper) => paper.paper_id === sourceId)) {
      setError("This linked paper is no longer saved in the project.");
      return;
    }
    rememberRecentProjectSource(project?.project_id, "paper", sourceId, sourceTitle);
    setScreeningQuery(sourceTitle);
    setScreeningFilter("all");
    setAnnotationPaperId(sourceId);
    setView("papers");
  }

  function openCrossProjectSearchResult(result: CrossProjectSearchResult) {
    const target = projects.find((item) => item.project_id === result.project_id);
    if (!target) {
      setError("This project is no longer available.");
      return;
    }
    setProject(target);
    setSelectedTeamWorkspaceId(target.team_workspace_id);
    setNotice("");
    setMobileNavigationOpen(false);
    if (result.source_type === "document") {
      openDocumentEvidence(
        result.source_id,
        null,
        result.excerpt,
        result.project_id,
        result.title,
      );
      setAnnotationPaperId(null);
      return;
    }
    rememberRecentProjectSource(result.project_id, "paper", result.source_id, result.title);
    setScreeningQuery(result.title);
    setScreeningFilter("all");
    setPaperMetadataFilters({ tag: "", metadataKey: "", metadataValue: "" });
    setAnnotationPaperId(result.source_id);
    setAnnotationDocumentId(null);
    setView("papers");
  }

  function openProjectAnnotation(annotation: ProjectAnnotation) {
    openProjectSource(annotation.source_type, annotation.source_type === "document"
      ? annotation.document_id ?? ""
      : annotation.paper_id ?? "", annotation.source_title);
  }

  function openProjectNotesFromInbox(projectId: string) {
    const target = projects.find((item) => item.project_id === projectId);
    if (!target) {
      setError("This project is no longer available.");
      return;
    }
    setProject(target);
    setSelectedTeamWorkspaceId(target.team_workspace_id);
    setView("notes");
    setShowInbox(false);
  }

  function openQuickNote() {
    if (!project || !canCommentOnProject) return;
    const firstSource = projectTaskSources[0];
    if (!firstSource) {
      setView("notes");
      setError("Add a project document or save a paper before creating a note.");
      return;
    }
    setQuickNoteSourceSelection(`${firstSource.source_type}.${firstSource.source_id}`);
    setQuickNoteText("");
    setQuickNoteError("");
    setError("");
    setNotice("");
    setView("notes");
    setMobileNavigationOpen(false);
    setShowQuickNote(true);
    window.setTimeout(() => quickNoteTextRef.current?.focus(), 0);
  }

  async function createQuickNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || !canCommentOnProject || quickNoteBusy) return;
    const selectedSource = projectTaskSources.find(
      (source) => `${source.source_type}.${source.source_id}` === quickNoteSourceSelection,
    );
    if (!selectedSource) {
      setQuickNoteError("Choose a project paper or document for this note.");
      return;
    }
    const note = quickNoteText.trim();
    if (!note) {
      setQuickNoteError("Write a note before saving.");
      return;
    }

    const projectId = project.project_id;
    setQuickNoteBusy(true);
    setQuickNoteError("");
    try {
      const sourceCollection = selectedSource.source_type === "document" ? "documents" : "papers";
      await request<Annotation>(
        `/api/projects/${projectId}/${sourceCollection}/${selectedSource.source_id}/annotations`,
        { method: "POST", body: jsonBody({ note }) },
      );
      if (selectedProjectIdRef.current !== projectId) return;
      setShowQuickNote(false);
      setQuickNoteText("");
      setNotice("Note saved.");
      try {
        const refreshedAnnotations = await request<ProjectAnnotation[]>(
          `/api/projects/${projectId}/annotations`,
        );
        if (selectedProjectIdRef.current === projectId) {
          setProjectAnnotations(refreshedAnnotations);
        }
      } catch (cause) {
        if (selectedProjectIdRef.current === projectId) {
          setError(
            cause instanceof Error
              ? `Note was saved, but project notes could not refresh: ${cause.message}`
              : "Note was saved, but project notes could not refresh.",
          );
        }
      }
    } catch (cause) {
      if (selectedProjectIdRef.current !== projectId) return;
      setQuickNoteError(cause instanceof Error ? cause.message : "Could not save this note.");
    } finally {
      if (selectedProjectIdRef.current === projectId) setQuickNoteBusy(false);
    }
  }

  async function updateProjectAnnotation(
    annotation: ProjectAnnotation,
    update: ProjectAnnotationUpdate,
  ): Promise<Annotation | null> {
    setAnnotationBusyIds((current) => new Set(current).add(annotation.annotation_id));
    setError("");
    try {
      const sourceId = annotation.source_type === "document"
        ? annotation.document_id
        : annotation.paper_id;
      if (!sourceId) throw new Error("The note's source is no longer available.");
      const updated = await api<Annotation>(
        `/api/projects/${annotation.project_id}/${annotation.source_type === "document" ? "documents" : "papers"}/${sourceId}/annotations/${annotation.annotation_id}`,
        { method: "PATCH", body: jsonBody(update) },
      );
      setProjectAnnotations((current) =>
        current.map((item) => item.annotation_id === updated.annotation_id ? { ...item, ...updated } : item),
      );
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update this note.");
      return null;
    } finally {
      setAnnotationBusyIds((current) => {
        const next = new Set(current);
        next.delete(annotation.annotation_id);
        return next;
      });
    }
  }

  async function createProjectTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!project || !selectedTaskSource || taskSaving) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setTaskSaving(true);
    setError("");
    try {
      const created = await request<ProjectTask>(`/api/projects/${project.project_id}/tasks`, {
        method: "POST",
        body: jsonBody({
          source_type: selectedTaskSource.source_type,
          source_id: selectedTaskSource.source_id,
          annotation_id: data.get("annotation_id") || null,
          title: data.get("title"),
          assignee_id: data.get("assignee_id"),
        }),
      });
      setProjectTasks((current) => [created, ...current]);
      setTaskAnnotationSelection("");
      form.reset();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the task.");
    } finally {
      setTaskSaving(false);
    }
  }

  async function updateProjectTask(
    task: ProjectTask,
    update: { status?: ProjectTask["status"]; assignee_id?: string | null },
  ) {
    if (!project) return;
    setTaskBusyId(task.task_id);
    setError("");
    try {
      const updated = await request<ProjectTask>(
        `/api/projects/${project.project_id}/tasks/${task.task_id}`,
        { method: "PATCH", body: jsonBody(update) },
      );
      setProjectTasks((current) => current.map((item) =>
        item.task_id === updated.task_id ? updated : item,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update the task.");
    } finally {
      setTaskBusyId(null);
    }
  }

  async function deleteProjectTask(task: ProjectTask) {
    if (!project) return;
    setTaskBusyId(task.task_id);
    setError("");
    try {
      await request<void>(`/api/projects/${project.project_id}/tasks/${task.task_id}`, {
        method: "DELETE",
      });
      setProjectTasks((current) => current.filter((item) => item.task_id !== task.task_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete the task.");
    } finally {
      setTaskBusyId(null);
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

  function openSource(source: Source, cardId: string) {
    if (source.kind === "document" && source.document_id) {
      if (!documents.some((document) => document.document_id === source.document_id)) {
        setError("This cited document is no longer available in the project.");
        return;
      }
      openDocumentEvidence(source.document_id, source.page_number, source.excerpt);
    } else {
      const card = document.getElementById(cardId);
      card?.scrollIntoView({ block: "center", behavior: "smooth" });
      card?.focus({ preventScroll: true });
    }
  }

  function reviseWithoutSource(source: Source, originalQuestion: string) {
    if (!originalQuestion) {
      setError("The original question is unavailable; enter a new question to revise this answer.");
      return;
    }
    setAssistantSources(withoutAssistantSource(allAssistantSources(documents, papers), source));
    setQuestion(originalQuestion);
    setDraft(null);
    setError("");
    setNotice("The cited source was excluded. Select different evidence and generate a new draft.");
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
    const exclusionReason: ScreeningExclusionReason | null =
      bulkScreeningStatus === "exclude" && bulkExclusionReason
        ? bulkExclusionReason
        : null;
    if (bulkScreeningStatus === "exclude" && !exclusionReason) {
      setError("Choose a structured exclusion reason before applying the decision.");
      return;
    }
    if (exclusionReason === "other" && !bulkScreeningNote.trim()) {
      setError("Add a note when the exclusion reason is Other.");
      return;
    }
    setScreeningBusy(true);
    setError("");
    try {
      const result = await request<{ updated_count: number }>(
        `/api/projects/${project.project_id}/papers/screening/bulk`,
        {
          method: "POST",
          body: jsonBody({
            paper_ids: paperIds,
            screening_status: bulkScreeningStatus,
            exclusion_reason: exclusionReason,
            ...(bulkScreeningStatus === "exclude" && bulkScreeningNote.trim()
              ? { screening_note: bulkScreeningNote.trim() }
              : {}),
          }),
        },
      );
      const updatedPaperIds = new Set(paperIds);
      setPapers((current) => current.map((paper) =>
        updatedPaperIds.has(paper.paper_id)
          ? {
            ...paper,
            screening_status: bulkScreeningStatus,
            screening_exclusion_reason: exclusionReason,
            ...(bulkScreeningStatus === "exclude" && bulkScreeningNote.trim()
              ? { screening_note: bulkScreeningNote.trim() }
              : {}),
          }
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

  async function openResearchPacket() {
    if (!project || researchPacketLoading) return;
    const projectId = project.project_id;
    setShowResearchPacket(true);
    setResearchPacketLoading(true);
    setResearchPacketError("");
    setError("");
    setNotice("");
    try {
      const [loadedPapers, loadedNotes, loadedOutputs] = await Promise.all([
        request<Paper[]>(`/api/projects/${projectId}/papers`),
        request<ProjectAnnotation[]>(`/api/projects/${projectId}/annotations`),
        request<ResearchPacketAssistantOutputOption[]>(
          `/api/projects/${projectId}/research-packet/assistant-outputs`,
        ),
      ]);
      if (selectedProjectIdRef.current !== projectId) return;
      setResearchPacketPapers(loadedPapers);
      setResearchPacketNotes(loadedNotes);
      setResearchPacketOutputs(loadedOutputs);
      setSelectedResearchPacketPaperIds(new Set(loadedPapers.map((paper) => paper.paper_id)));
      setSelectedResearchPacketNoteIds(
        new Set(loadedNotes.map((annotation) => annotation.annotation_id)),
      );
      setSelectedResearchPacketOutputIds(
        new Set(loadedOutputs.map((output) => output.message_id)),
      );
    } catch (cause) {
      if (selectedProjectIdRef.current !== projectId) return;
      setResearchPacketError(
        cause instanceof Error ? cause.message : "Could not load research packet options.",
      );
    } finally {
      if (selectedProjectIdRef.current === projectId) setResearchPacketLoading(false);
    }
  }

  async function exportResearchPacket() {
    if (!project || researchPacketBusy) return;
    const projectId = project.project_id;
    const body = {
      paper_ids: [...selectedResearchPacketPaperIds],
      annotation_ids: [...selectedResearchPacketNoteIds],
      assistant_message_ids: [...selectedResearchPacketOutputIds],
    };
    if (
      body.paper_ids.length > 100
      || body.annotation_ids.length > 500
      || body.assistant_message_ids.length > 100
    ) {
      setResearchPacketError(
        "A packet can contain up to 100 papers, 500 notes, and 100 approved responses.",
      );
      return;
    }
    if (!body.paper_ids.length && !body.annotation_ids.length && !body.assistant_message_ids.length) {
      setResearchPacketError("Select at least one paper, note, or approved assistant output.");
      return;
    }
    setResearchPacketBusy(true);
    setResearchPacketError("");
    setError("");
    setNotice("");
    try {
      await downloadFile(
        `/api/projects/${projectId}/research-packet`,
        "research-packet.zip",
        { method: "POST", body: jsonBody(body) },
      );
      if (selectedProjectIdRef.current !== projectId) return;
      setShowResearchPacket(false);
      setNotice("Research packet downloaded.");
    } catch (cause) {
      if (selectedProjectIdRef.current !== projectId) return;
      setResearchPacketError(
        cause instanceof Error ? cause.message : "Could not export this research packet.",
      );
    } finally {
      if (selectedProjectIdRef.current === projectId) setResearchPacketBusy(false);
    }
  }

  function closeSourceSummary() {
    sourceSummaryRequestIdRef.current += 1;
    setSourceSummary(null);
  }

  async function summarizeProjectSource(
    sourceType: "document" | "paper",
    sourceId: string,
    title: string,
  ) {
    if (!project) return;
    const projectId = project.project_id;
    const requestId = ++sourceSummaryRequestIdRef.current;
    setSourceSummary({ title, summary: null, cached: false, loading: true, error: "" });
    try {
      const result = await request<SourceSummaryResponse>(
        `/api/projects/${projectId}/source-summaries`,
        {
          method: "POST",
          body: jsonBody({ source_type: sourceType, source_id: sourceId }),
        },
      );
      if (sourceSummaryRequestIdRef.current !== requestId
        || selectedProjectIdRef.current !== projectId) return;
      setSourceSummary({
        title: result.title,
        summary: result.summary,
        cached: result.cached,
        loading: false,
        error: "",
      });
    } catch (cause) {
      if (sourceSummaryRequestIdRef.current !== requestId
        || selectedProjectIdRef.current !== projectId) return;
      setSourceSummary({
        title,
        summary: null,
        cached: false,
        loading: false,
        error: cause instanceof Error ? cause.message : "Could not summarize this source.",
      });
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
    const queued: UploadQueueItem[] = files.map((file) => ({
      key: crypto.randomUUID(),
      projectId: project.project_id,
      file,
      filename: file.name,
      status: "uploading" as const,
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

  async function updateDocumentMetadata(
    documentId: string,
    tags: string[],
    metadata: Record<string, string>,
  ) {
    if (!project) return;
    setError("");
    try {
      const updated = await request<DocumentRecord>(
        `/api/documents/${documentId}/metadata`,
        { method: "PATCH", body: jsonBody({ tags, metadata }) },
      );
      setDocuments((current) => current.map((document) =>
        document.document_id === documentId ? updated : document,
      ));
      setNotice("Document tags and metadata saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save document metadata.");
      throw cause;
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

  async function runPaperSearch(queryText: string, searchProvider: string, limit = 10) {
    if (!project || queryText.trim().length < 2 || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await request<SearchResult>(
        `/api/projects/${project.project_id}/papers/search?q=${encodeURIComponent(queryText.trim())}&provider=${searchProvider}&limit=${limit}`,
      );
      setSearchResults(result);
      setSearchHistory((current) => [
        {
          query_id: result.query_id,
          query_text: result.query,
          api_provider: result.provider,
          searched_at: result.searched_at,
          search_filters: result.filters,
          result_count: result.result_count,
        },
        ...current.filter((record) => record.query_id !== result.query_id),
      ].slice(0, 20));
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

  async function rerunSearchHistory(record: SearchQueryHistoryRecord) {
    if (busy) return;
    const search = literatureSearchRequest(record);
    setSearchText(search.query);
    setProvider(search.provider);
    await runPaperSearch(search.query, search.provider, search.limit);
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
      setSearchHistory((current) => [
        {
          query_id: result.query_id,
          query_text: result.query,
          api_provider: result.provider,
          searched_at: result.searched_at,
          search_filters: result.filters,
          result_count: result.result_count,
        },
        ...current.filter((record) => record.query_id !== result.query_id),
      ].slice(0, 20));
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

  function reviewPaperBeforeSave(paper: Paper) {
    if (!project || !canEditProject) return;
    const matches = findPaperSimilarityMatches(paper, papers);
    if (matches.length) {
      setPendingPaperSave({ projectId: project.project_id, paper, matches });
      return;
    }
    void savePaper(paper);
  }

  function confirmPaperSave() {
    const pending = pendingPaperSave;
    setPendingPaperSave(null);
    if (!pending || project?.project_id !== pending.projectId) return;
    void savePaper(pending.paper);
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
    exclusionReason: ScreeningExclusionReason | null,
  ) {
    if (!project) return;
    setError("");
    try {
      const updated = await request<{
        screening_status: Paper["screening_status"];
        screening_note: string;
        exclusion_reason: ScreeningExclusionReason | null;
      }>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/screening`,
        {
          method: "PATCH",
          body: jsonBody({
            screening_status: screeningStatus,
            screening_note: screeningNote,
            exclusion_reason: exclusionReason,
          }),
        },
      );
      setPapers((current) => current.map((item) =>
        item.paper_id === paper.paper_id
          ? {
            ...item,
            screening_status: updated.screening_status,
            screening_note: updated.screening_note,
            screening_exclusion_reason: updated.exclusion_reason,
          }
          : item,
      ));
      setNotice("Screening decision saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this screening decision.");
    }
  }

  async function updateReviewerScreeningDecision(
    paper: Paper,
    screeningStatus: PaperScreeningDecision["screening_status"],
    exclusionReason: ScreeningExclusionReason | null,
    screeningNote: string,
  ): Promise<PaperScreeningDecision> {
    if (!project || !user) throw new Error("Sign in to save a reviewer decision.");
    setError("");
    try {
      const updated = await request<PaperScreeningDecision>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/screening/decision`,
        {
          method: "PATCH",
          body: jsonBody({
            screening_status: screeningStatus,
            exclusion_reason: exclusionReason,
            screening_note: screeningNote,
          }),
        },
      );
      setPapers((current) => current.map((item) => {
        if (item.paper_id !== paper.paper_id) return item;
        const decisions = [
          ...item.screening_decisions.filter((decision) => decision.user_id !== updated.user_id),
          updated,
        ].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
        return {
          ...item,
          screening_decisions: decisions,
          screening_disagreement: hasScreeningDisagreement(decisions),
        };
      }));
      setNotice("Your reviewer decision was saved.");
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your reviewer decision.");
      throw cause;
    }
  }

  async function updatePaperScreeningAssignments(
    paper: Paper,
    userIds: string[],
  ): Promise<PaperScreeningAssignment[]> {
    if (!project) throw new Error("Select a project to assign reviewers.");
    setError("");
    try {
      const updated = await request<PaperScreeningAssignment[]>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/screening/assignments`,
        {
          method: "PUT",
          body: jsonBody({ user_ids: userIds }),
        },
      );
      setPapers((current) => current.map((item) =>
        item.paper_id === paper.paper_id
          ? { ...item, screening_assignments: updated }
          : item,
      ));
      setNotice("Review assignments saved.");
      return updated;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save review assignments.");
      throw cause;
    }
  }

  async function updatePaperMetadata(
    paper: Paper,
    tags: string[],
    metadata: Record<string, string>,
  ) {
    if (!project) return;
    setError("");
    try {
      const updated = await request<Pick<Paper, "tags" | "metadata">>(
        `/api/projects/${project.project_id}/papers/${paper.paper_id}/metadata`,
        { method: "PATCH", body: jsonBody({ tags, metadata }) },
      );
      setPapers((current) => current.map((item) =>
        item.paper_id === paper.paper_id ? { ...item, ...updated } : item,
      ));
      setNotice("Paper tags and metadata saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save paper metadata.");
      throw cause;
    }
  }

  async function savePaperStudyExtraction(
    paperId: string,
    values: StudyExtractionValues,
    expectedUpdatedAt: string | null,
  ): Promise<PaperStudyExtraction> {
    if (!project || !canEditProject) {
      throw new Error("Editor access is required to save study extractions.");
    }
    const projectId = project.project_id;
    const saved = await request<PaperStudyExtraction>(
      `/api/projects/${projectId}/papers/${paperId}/extraction`,
      {
        method: "PUT",
        body: jsonBody({ ...values, expected_updated_at: expectedUpdatedAt }),
      },
    );
    if (selectedProjectIdRef.current === projectId) {
      setPapers((current) => current.map((paper) =>
        paper.paper_id === paperId ? { ...paper, study_extraction: saved } : paper,
      ));
      setNotice("Study extraction saved.");
    }
    return saved;
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
    if (assistantSources && !assistantSources.document_ids.length && !assistantSources.paper_ids.length) {
      setError("Select at least one source for this question.");
      return;
    }
    const submittedQuestion = question.trim();
    setBusy(true);
    setError("");
    setNotice("");
    setDraft(null);
    try {
      const generated = await request<Draft>(`/api/projects/${project.project_id}/assistant/draft`, {
        method: "POST",
        body: jsonBody({
          question: submittedQuestion,
          mode: askMode,
          conversation_id: conversation?.conversation_id ?? null,
          source_selection: assistantSources,
        }),
      });
      setDraft(generated);
      setDraftQuestion(submittedQuestion);
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
    setView("home");
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
      {project && canEditProject && (
        <input
          ref={uploadInputRef}
          hidden
          name="files"
          type="file"
          accept=".pdf,.docx,.txt,.md"
          multiple
          disabled={uploadingFiles}
          aria-label="Upload project documents"
          onChange={(event) => {
            const files = Array.from(event.currentTarget.files ?? []);
            if (files.length) void uploadDocuments(files);
            event.currentTarget.value = "";
          }}
        />
      )}
      <aside id="app-navigation" className={`sidebar ${mobileNavigationOpen ? "mobile-open" : ""}`}>
        <a className="brand" href="#" aria-label="Fieldnotes home">
          <span className="brand-mark"><BookOpen size={19} /></span>
          <span>fieldnotes<span className="brand-dot">.</span></span>
        </a>
        <button
          type="button"
          className="icon-button mobile-nav-close"
          aria-label="Close navigation"
          onClick={() => setMobileNavigationOpen(false)}
        >
          <X size={18} />
        </button>
        <div className="sidebar-label">WORKSPACE</div>
        <button className="new-project-button" onClick={() => {
          setShowNewProject(true);
          setMobileNavigationOpen(false);
        }}>
          <FolderPlus size={16} /> New {selectedTeamWorkspaceId ? "team project" : "project"} <Plus size={15} className="push-right" />
        </button>
        <div className="sidebar-team-heading">
          <span className="sidebar-label">WORKSPACES</span>
          <button
            className="workspace-manage-button"
            title="Manage workspaces"
            onClick={() => {
              setShowTeamWorkspaces(true);
              setMobileNavigationOpen(false);
            }}
          >
            <Settings size={13} /> Manage
          </button>
        </div>
        <nav className="team-workspace-list" aria-label="Team workspaces">
          <button
            className={`team-workspace-link ${selectedTeamWorkspaceId === null ? "selected" : ""}`}
            onClick={() => {
              switchTeamWorkspace(null);
              setMobileNavigationOpen(false);
            }}
            type="button"
          >
            <Users size={14} /><span>Personal &amp; shared</span>
          </button>
          {teamWorkspaces.map((workspace) => (
            <button
              className={`team-workspace-link ${selectedTeamWorkspaceId === workspace.team_workspace_id ? "selected" : ""}`}
              key={workspace.team_workspace_id}
              onClick={() => {
                switchTeamWorkspace(workspace.team_workspace_id);
                setMobileNavigationOpen(false);
              }}
              type="button"
            >
              <Users size={14} /><span>{workspace.name}</span>
            </button>
          ))}
        </nav>
        <button
          className={`project-link global-search-link${view === "search" ? " selected" : ""}`}
          type="button"
          aria-current={view === "search" ? "page" : undefined}
          aria-keyshortcuts="Control+K Meta+K"
          title="Search all projects (Ctrl/Cmd+K)"
          onClick={() => {
            setView("search");
            setMobileNavigationOpen(false);
          }}
        >
          <Search size={15} /><span className="project-link-name">Search all projects</span>
        </button>
        <div className="sidebar-project-heading">
          <span className="sidebar-label">PROJECTS</span>
          <span className="project-count">{visibleProjects.length}</span>
        </div>
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
                setView("home");
                setNotice("");
                setMobileNavigationOpen(false);
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
              setMobileNavigationOpen(false);
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
          <button className="icon-button logout" title="Sign out" aria-label="Sign out" onClick={signOut}>
            <LogOut size={16} /><span>Sign out</span>
          </button>
        </div>
      </aside>

      {mobileNavigationOpen && (
        <button
          type="button"
          className="mobile-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNavigationOpen(false)}
        />
      )}

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-leading">
            <button
              type="button"
              className="icon-button mobile-nav-toggle"
              aria-label={mobileNavigationOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={mobileNavigationOpen}
              aria-controls="app-navigation"
              onClick={() => setMobileNavigationOpen((open) => !open)}
            >
              {mobileNavigationOpen ? <X size={19} /> : <Menu size={19} />}
            </button>
            <div className="breadcrumb">
            <span>Workspace</span><span className="crumb-separator">/</span>
            <span className="crumb-current">{view === "search" ? "Search all projects" : project?.project_name ?? "No project selected"}</span>
            </div>
          </div>
          <div className="topbar-right">
            {view !== "search" && <span className="private-badge">
              {project?.team_workspace_id
                ? <><Users size={14} /> Team workspace</>
                : project && user && project.user_id !== user.user_id
                  ? <><Users size={14} /> Shared project</>
                  : <><ShieldCheck size={14} /> Private workspace</>}
            </span>}
            <button
              className="icon-button topbar-action inbox-button"
              title="Inbox and messages"
              aria-label="Inbox and messages"
              onClick={() => setShowInbox(true)}
            >
              <Bell size={17} />
              <span className="topbar-action-label">Inbox</span>
              {unreadCount > 0 && <span className="unread-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>}
            </button>
            {project && (
              <WorkStatusPanel
                key={project.project_id}
                items={workStatusItems}
                projectName={project.project_name}
              />
            )}
            {channelWorkspaceId && (
              <button
                className="icon-button topbar-action"
                title="Team channels"
                aria-label="Team channels"
                onClick={() => setShowTeamChannels(true)}
              >
                <MessageSquareText size={16} />
                <span className="topbar-action-label">Channels</span>
              </button>
            )}
            <button
              className="icon-button topbar-action"
              title="Team workspaces"
              aria-label="Team workspaces"
              onClick={() => setShowTeamWorkspaces(true)}
            >
              <Users size={16} />
              <span className="topbar-action-label">Teams</span>
            </button>
            {project && view !== "search" && (
              <>
                {user && project.user_id === user.user_id && (
                  <button
                    className="icon-button topbar-action"
                    title="Share project"
                    aria-label="Share project"
                    onClick={() => setShowShareProject(true)}
                  >
                    <Share2 size={16} /><span className="topbar-action-label">Share</span>
                  </button>
                )}
                {user && project.user_id === user.user_id && (
                  <button
                    className="icon-button topbar-action danger-hover"
                    title="Delete project"
                    aria-label="Delete project"
                    onClick={deleteProject}
                  >
                    <Trash2 size={16} /><span className="topbar-action-label">Delete</span>
                  </button>
                )}
              </>
            )}
          </div>
        </header>

        <div className="content-area">
          {error && <Notice kind="error" text={error} onClose={() => setError("")} />}
          {notice && <Notice kind="success" text={notice} onClose={() => setNotice("")} />}
          {pendingPaperSave && project?.project_id === pendingPaperSave.projectId && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget) setPendingPaperSave(null);
            }}>
              <section
                className="modal-card paper-match-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="paper-match-title"
                aria-describedby="paper-match-description"
                onKeyDown={(event) => {
                  if (event.key === "Escape") setPendingPaperSave(null);
                }}
              >
                <div className="modal-heading">
                  <div>
                    <p className="eyebrow">CHECK YOUR LIBRARY</p>
                    <h2 id="paper-match-title">Possible duplicates or related papers</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setPendingPaperSave(null)}
                    aria-label="Close"
                    autoFocus
                  >
                    <X size={18} />
                  </button>
                </div>
                <p id="paper-match-description" className="paper-match-intro">
                  These saved papers have a matching DOI or a similar title. Metadata can differ,
                  and papers without a DOI can still match. Review them before adding{" "}
                  <strong>{pendingPaperSave.paper.title}</strong>.
                </p>
                <ul className="paper-match-list">
                  {pendingPaperSave.matches.map((match) => (
                    <li key={match.paper.paper_id} className="paper-match-item">
                      <div className="paper-match-heading">
                        <strong>{match.paper.title}</strong>
                        <span className={`paper-match-badge ${match.kind}`}>
                          {match.kind === "possible_duplicate" ? "Possible duplicate" : "Related"}
                        </span>
                      </div>
                      <p>{match.reason}</p>
                      <small>
                        {[
                          match.paper.authors.map((author) => author.author_name).join(", "),
                          match.paper.publication_year,
                          match.paper.doi ? `DOI: ${match.paper.doi}` : null,
                        ].filter(Boolean).join(" · ") || "No additional metadata"}
                      </small>
                      {match.paper.paper_url && (
                        <a href={match.paper.paper_url} target="_blank" rel="noreferrer">
                          Open saved paper
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="paper-match-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setPendingPaperSave(null)}
                  >
                    Cancel
                  </button>
                  <button type="button" className="button primary" onClick={confirmPaperSave}>
                    Save anyway
                  </button>
                </div>
                <p className="paper-match-footnote">Saving anyway keeps both records in the project.</p>
              </section>
            </div>
          )}
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
          {showResearchPacket && project && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget && !researchPacketBusy) {
                setShowResearchPacket(false);
              }
            }}>
              <section
                className="modal-card research-packet-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="research-packet-title"
                aria-busy={researchPacketLoading || researchPacketBusy}
              >
                <div className="modal-heading">
                  <div>
                    <p className="eyebrow">SELECTED PROJECT MATERIALS</p>
                    <h2 id="research-packet-title">Export research packet</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setShowResearchPacket(false)}
                    aria-label="Close"
                    disabled={researchPacketBusy}
                  >
                    <X size={18} />
                  </button>
                </div>
                <p className="muted">
                  Choose papers, notes, and approved assistant responses. The ZIP includes
                  reference files and citations for selected responses; only your own approved
                  outputs are available. Each packet supports up to 100 papers, 500 notes, and
                  100 approved responses.
                </p>
                {researchPacketError && (
                  <p className="project-export-error" role="alert">{researchPacketError}</p>
                )}
                {researchPacketLoading ? (
                  <p className="source-summary-loading">
                    <LoaderCircle className="spin" size={14} /> Loading packet options…
                  </p>
                ) : (
                  <div className="research-packet-sections">
                    <fieldset className="research-packet-group">
                      <legend>Saved papers ({researchPacketPapers.length})</legend>
                      {researchPacketPapers.length ? (
                        <div className="research-packet-options">
                          {researchPacketPapers.map((paper) => (
                            <label className="research-packet-option" key={paper.paper_id}>
                              <input
                                type="checkbox"
                                checked={selectedResearchPacketPaperIds.has(paper.paper_id)}
                                disabled={researchPacketBusy}
                                onChange={() => setSelectedResearchPacketPaperIds((current) => {
                                  const next = new Set(current);
                                  if (next.has(paper.paper_id)) next.delete(paper.paper_id);
                                  else next.add(paper.paper_id);
                                  return next;
                                })}
                              />
                              <span>
                                <strong>{paper.title}</strong>
                                <small>
                                  {paper.authors.slice(0, 3).map((author) => author.author_name).join(", ")
                                    || "Author unavailable"}
                                  {paper.publication_year ? ` · ${paper.publication_year}` : ""}
                                </small>
                              </span>
                            </label>
                          ))}
                        </div>
                      ) : <p className="muted">No saved papers in this project.</p>}
                    </fieldset>
                    <fieldset className="research-packet-group">
                      <legend>Project notes ({researchPacketNotes.length})</legend>
                      {researchPacketNotes.length ? (
                        <div className="research-packet-options">
                          {researchPacketNotes.map((annotation) => (
                            <label className="research-packet-option" key={annotation.annotation_id}>
                              <input
                                type="checkbox"
                                checked={selectedResearchPacketNoteIds.has(annotation.annotation_id)}
                                disabled={researchPacketBusy}
                                onChange={() => setSelectedResearchPacketNoteIds((current) => {
                                  const next = new Set(current);
                                  if (next.has(annotation.annotation_id)) next.delete(annotation.annotation_id);
                                  else next.add(annotation.annotation_id);
                                  return next;
                                })}
                              />
                              <span>
                                <strong>{annotation.source_title}</strong>
                                <small>{annotation.note || annotation.quote || "Highlight"} · {annotation.tags.join(", ") || "Untagged"}</small>
                              </span>
                            </label>
                          ))}
                        </div>
                      ) : <p className="muted">No project notes are available.</p>}
                    </fieldset>
                    <fieldset className="research-packet-group">
                      <legend>Approved assistant responses ({researchPacketOutputs.length})</legend>
                      {researchPacketOutputs.length ? (
                        <div className="research-packet-options">
                          {researchPacketOutputs.map((output) => (
                            <label className="research-packet-option" key={output.message_id}>
                              <input
                                type="checkbox"
                                checked={selectedResearchPacketOutputIds.has(output.message_id)}
                                disabled={researchPacketBusy}
                                onChange={() => setSelectedResearchPacketOutputIds((current) => {
                                  const next = new Set(current);
                                  if (next.has(output.message_id)) next.delete(output.message_id);
                                  else next.add(output.message_id);
                                  return next;
                                })}
                              />
                              <span>
                                <strong>{output.conversation_title} · {new Date(output.created_at).toLocaleDateString()}</strong>
                                <small>{output.excerpt}</small>
                              </span>
                            </label>
                          ))}
                        </div>
                      ) : <p className="muted">No approved assistant responses are available.</p>}
                    </fieldset>
                  </div>
                )}
                <div className="project-export-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setShowResearchPacket(false)}
                    disabled={researchPacketBusy}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button primary"
                    onClick={() => void exportResearchPacket()}
                    disabled={
                      researchPacketLoading
                      || researchPacketBusy
                      || !(selectedResearchPacketPaperIds.size
                        + selectedResearchPacketNoteIds.size
                        + selectedResearchPacketOutputIds.size)
                    }
                  >
                    <Download size={15} />
                    {researchPacketBusy ? "Preparing packet…" : "Download research packet"}
                  </button>
                </div>
              </section>
            </div>
          )}
          {sourceSummary && (
            <div className="modal-backdrop" onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeSourceSummary();
            }}>
              <section
                className="modal-card source-summary-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="source-summary-title"
                aria-busy={sourceSummary.loading}
              >
                <div className="modal-heading">
                  <div>
                    <p className="eyebrow">AI SOURCE SUMMARY</p>
                    <h2 id="source-summary-title">{sourceSummary.title}</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={closeSourceSummary}
                    aria-label="Close summary"
                  >
                    <X size={18} />
                  </button>
                </div>
                {sourceSummary.loading ? (
                  <p className="source-summary-loading" role="status">
                    <LoaderCircle size={16} className="spin" /> Summarizing source…
                  </p>
                ) : sourceSummary.error ? (
                  <p className="source-summary-error" role="alert">{sourceSummary.error}</p>
                ) : (
                  <>
                    <div className="source-summary-text">{sourceSummary.summary}</div>
                    <p className="source-summary-saved">
                      {sourceSummary.cached
                        ? "Saved summary reused."
                        : "Summary saved for this source and reused next time."}
                    </p>
                  </>
                )}
              </section>
            </div>
          )}
          {showInbox && (
            <InboxDialog
              request={request}
              onClose={() => setShowInbox(false)}
              onProjectsUpdated={refreshProjects}
              onUnreadCount={refreshUnreadCount}
              onOpenProject={openProjectNotesFromInbox}
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
          {showQuickNote && project && (
            <div
              className="modal-backdrop"
              onMouseDown={(event) => {
                if (event.target === event.currentTarget && !quickNoteBusy) {
                  setShowQuickNote(false);
                }
              }}
            >
              <form
                className="modal-card stack-form quick-note-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="quick-note-title"
                aria-busy={quickNoteBusy}
                onSubmit={(event) => void createQuickNote(event)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && !quickNoteBusy) {
                    event.stopPropagation();
                    setShowQuickNote(false);
                  }
                }}
              >
                <div className="modal-heading">
                  <div>
                    <p className="eyebrow">PROJECT NOTES</p>
                    <h2 id="quick-note-title">New note</h2>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Close new note"
                    disabled={quickNoteBusy}
                    onClick={() => setShowQuickNote(false)}
                  >
                    <X size={18} />
                  </button>
                </div>
                <p className="muted">
                  Choose a saved paper or project document to attach this note to.
                </p>
                {quickNoteError && <p className="inline-error" role="alert">{quickNoteError}</p>}
                <label>
                  Source
                  <select
                    value={quickNoteSourceSelection}
                    onChange={(event) => setQuickNoteSourceSelection(event.target.value)}
                    disabled={quickNoteBusy}
                    required
                  >
                    <option value="" disabled>Choose a project source…</option>
                    {projectTaskSources.map((source) => (
                      <option
                        key={`${source.source_type}.${source.source_id}`}
                        value={`${source.source_type}.${source.source_id}`}
                      >
                        {source.source_type === "document" ? "Document" : "Paper"}: {source.source_title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Note
                  <textarea
                    ref={quickNoteTextRef}
                    value={quickNoteText}
                    onChange={(event) => setQuickNoteText(event.target.value)}
                    maxLength={5000}
                    rows={5}
                    required
                    disabled={quickNoteBusy}
                    placeholder="Write a note for your synthesis…"
                  />
                </label>
                <div className="project-export-actions">
                  <button
                    type="button"
                    className="button secondary"
                    disabled={quickNoteBusy}
                    onClick={() => setShowQuickNote(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="button primary"
                    disabled={quickNoteBusy || !projectTaskSources.length || !quickNoteText.trim()}
                  >
                    {quickNoteBusy ? "Saving…" : "Save note"}
                  </button>
                </div>
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

          {view === "search" ? (
            <CrossProjectSearch
              projects={projects}
              request={request}
              onOpen={openCrossProjectSearchResult}
            />
          ) : !project ? (
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
                  <button className="button secondary small-button" onClick={() => void openResearchPacket()}>
                    <Download size={14} /> Research packet
                  </button>
                  {user && project.user_id === user.user_id && (
                    <button className="button secondary small-button edit-project" onClick={() => setShowEditProject(true)}>
                      <Pencil size={14} /> Edit
                    </button>
                  )}
                </div>
              </section>

              <div className="tab-bar" role="tablist" aria-label="Project sections">
                <TabButton active={view === "home"} onClick={() => setView("home")} shortcut="Ctrl/Cmd+Alt+1" ariaKeyShortcuts="Control+Alt+1 Meta+Alt+1" icon={<LayoutDashboard size={16} />}>Home</TabButton>
                <TabButton active={view === "documents"} onClick={() => setView("documents")} shortcut="Ctrl/Cmd+Alt+2" ariaKeyShortcuts="Control+Alt+2 Meta+Alt+2" icon={<FileText size={16} />}>Documents</TabButton>
                <TabButton active={view === "papers"} onClick={() => setView("papers")} shortcut="Ctrl/Cmd+Alt+3" ariaKeyShortcuts="Control+Alt+3 Meta+Alt+3" icon={<Library size={16} />}>Literature</TabButton>
                <TabButton active={view === "collections"} onClick={() => setView("collections")} shortcut="Ctrl/Cmd+Alt+4" ariaKeyShortcuts="Control+Alt+4 Meta+Alt+4" icon={<FolderPlus size={16} />}>Collections</TabButton>
                <TabButton active={view === "notes"} onClick={() => setView("notes")} shortcut="Ctrl/Cmd+Alt+5" ariaKeyShortcuts="Control+Alt+5 Meta+Alt+5" icon={<BookOpen size={16} />}>Notes</TabButton>
                <TabButton active={view === "latex"} onClick={() => setView("latex")} shortcut="Ctrl/Cmd+Alt+6" ariaKeyShortcuts="Control+Alt+6 Meta+Alt+6" icon={<FileCode2 size={16} />}>Main document</TabButton>
                <TabButton active={view === "assistant"} onClick={() => setView("assistant")} shortcut="Ctrl/Cmd+Alt+7" ariaKeyShortcuts="Control+Alt+7 Meta+Alt+7" icon={<MessageSquareText size={16} />}>Ask & explore</TabButton>
              </div>

              <div className={view === "latex" ? "" : "latex-workspace-hidden"} aria-hidden={view !== "latex"}>
                <LatexWorkspace
                  key={project.project_id}
                  project={project}
                  documents={documents}
                  papers={papers}
                  request={request}
                  onCompileStatusChange={reportLatexCompileActivity}
                />
              </div>

              {view === "home" && (
                <ProjectHome
                  key={`${user?.user_id}:${project.project_id}`}
                  projectId={project.project_id}
                  documents={documents}
                  recentSources={
                    recentSources.userId === user?.user_id
                    && recentSources.projectId === project.project_id
                      ? recentSources.sources
                      : []
                  }
                  recentSourcesError={
                    recentSourcesError.userId === user?.user_id
                    && recentSourcesError.projectId === project.project_id
                      ? recentSourcesError.message
                      : ""
                  }
                  request={request}
                  onOpenSource={openProjectSource}
                />
              )}

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
                        projectId={project.project_id}
                        annotationsPath={`/api/projects/${project.project_id}/documents/${openedDocument.document_id}/annotations`}
                        sourcePath={`/api/documents/${openedDocument.document_id}/reader`}
                        sourceStatus={openedDocument.processing_status}
                        citationExcerpt={openedDocument.file_type === "pdf" ? null : citationExcerpt}
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
                          <button
                            type="button"
                            className="button primary upload-button"
                            aria-keyshortcuts="Control+Alt+U Meta+Alt+U"
                            title="Upload documents (Ctrl/Cmd+Alt+U)"
                            disabled={uploadingFiles}
                            onClick={() => uploadInputRef.current?.click()}
                          >
                            <Upload size={16} /> {uploadingFiles ? "Uploading…" : "Add documents"}
                          </button>
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
                      {!!documents.length && (
                        <LibraryMetadataFilters
                          kind="documents"
                          filters={documentMetadataFilters}
                          onChange={setDocumentMetadataFilters}
                        />
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
                          {visibleDocuments.map((document) => (
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
                                <LibraryMetadataEditor
                                  tags={document.tags}
                                  metadata={document.metadata}
                                  canEdit={canEditProject}
                                  onSave={(tags, metadata) =>
                                    updateDocumentMetadata(document.document_id, tags, metadata)}
                                />
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
                          {visibleDocuments.length === 0 && (
                            <p className="muted compact library-metadata-empty">
                              No documents match these tag and metadata filters.
                            </p>
                          )}
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
                      <p>Tag and pin notes, connect related sources, assign source tasks, and mention collaborators with @username.</p>
                    </div>
                    <div className="project-heading-actions notes-heading-actions">
                      <button
                        type="button"
                        className="button secondary"
                        disabled={!canCommentOnProject || !projectTaskSources.length}
                        aria-keyshortcuts="Control+Alt+N Meta+Alt+N"
                        title="New note (Ctrl/Cmd+Alt+N)"
                        onClick={openQuickNote}
                      >
                        <Plus size={15} /> New note
                      </button>
                      <button
                        className="button primary"
                        disabled={!selectedProjectAnnotationCount}
                        onClick={useSelectedAnnotationsInAssistant}
                      >
                        <MessageSquareText size={15} /> Use selected in comparison ({selectedProjectAnnotationCount})
                      </button>
                    </div>
                  </div>
                  <section className="project-task-panel" aria-labelledby="project-task-heading">
                    <div className="project-task-heading">
                      <div>
                        <h3 id="project-task-heading">Team tasks</h3>
                        <p>Assign a paper or document review, optionally linking it to a note.</p>
                      </div>
                    </div>
                    {canCommentOnProject && projectTaskSources.length > 0 && (
                      <form className="project-task-form" onSubmit={(event) => void createProjectTask(event)}>
                        <select
                          name="source"
                          aria-label="Task paper or document"
                          value={resolvedTaskSourceSelection}
                          onChange={(event) => {
                            setTaskSourceSelection(event.target.value);
                            setTaskAnnotationSelection("");
                          }}
                          required
                        >
                          {projectTaskSources.map((source) => (
                            <option
                              key={`${source.source_type}.${source.source_id}`}
                              value={`${source.source_type}.${source.source_id}`}
                            >
                              {source.source_type === "document" ? "Document" : "Paper"}: {source.source_title}
                            </option>
                          ))}
                        </select>
                        <select
                          name="annotation_id"
                          aria-label="Link task to a note (optional)"
                          value={taskAnnotationSelection}
                          onChange={(event) => setTaskAnnotationSelection(event.target.value)}
                        >
                          <option value="">No linked note</option>
                          {taskAnnotationOptions.map((annotation) => (
                            <option key={annotation.annotation_id} value={annotation.annotation_id}>
                              {annotation.quote || annotation.note || "Highlight"} · {annotation.source_title}
                            </option>
                          ))}
                        </select>
                        <input
                          name="title"
                          aria-label="Task title"
                          placeholder="e.g. Review this paper"
                          maxLength={240}
                          required
                        />
                        <select
                          name="assignee_id"
                          aria-label="Assign task to"
                          required
                          value={resolvedTaskAssigneeSelection}
                          onChange={(event) => setTaskAssigneeSelection(event.target.value)}
                        >
                          <option value="" disabled>Assign to…</option>
                          {projectCollaborators.map((collaborator) => (
                            <option key={collaborator.user_id} value={collaborator.user_id}>
                              {collaborator.name} (@{collaborator.username})
                            </option>
                          ))}
                        </select>
                        <button className="button primary small-button" disabled={taskSaving}>
                          {taskSaving ? "Assigning…" : "Assign task"}
                        </button>
                      </form>
                    )}
                    {!canCommentOnProject && <p className="muted compact">Comment access is required to create project tasks.</p>}
                    {!projectTaskSources.length && <p className="muted compact">Add a project document or saved paper to create a task.</p>}
                    {projectTasks.length > 0 ? (
                      <div className="project-task-list">
                        {projectTasks.map((task) => {
                          const isOwner = project.access_role === "owner";
                          const isCreator = task.created_by === user?.user_id;
                          const isAssignee = task.assignee_id === user?.user_id;
                          const canUpdateStatus = isOwner || isCreator || isAssignee;
                          const canReassign = isOwner || isCreator;
                          const taskBusy = taskBusyId === task.task_id;
                          const linkedAnnotation = task.annotation_id
                            ? projectAnnotations.find((annotation) => annotation.annotation_id === task.annotation_id)
                            : null;
                          return (
                            <article className="project-task-item" key={task.task_id}>
                              <div className="project-task-copy">
                                <strong>{task.title}</strong>
                                <button
                                  type="button"
                                  className="project-task-source"
                                  onClick={() => openProjectSource(task.source_type, task.source_id, task.source_title)}
                                >
                                  {task.source_type === "document" ? "Document" : "Paper"}: {task.source_title}
                                </button>
                                {linkedAnnotation && (
                                  <small>Note: {linkedAnnotation.quote || linkedAnnotation.note}</small>
                                )}
                                <small>
                                  Assigned to {task.assignee_name ?? "nobody"} · Created by {task.created_by_name}
                                </small>
                              </div>
                              <select
                                aria-label={`Status for task ${task.title}`}
                                value={task.status}
                                disabled={!canUpdateStatus || taskBusy}
                                onChange={(event) => void updateProjectTask(
                                  task,
                                  { status: event.target.value as ProjectTask["status"] },
                                )}
                              >
                                <option value="open">Open</option>
                                <option value="in_progress">In progress</option>
                                <option value="done">Done</option>
                              </select>
                              {canReassign && (
                                <select
                                  aria-label={`Assignee for task ${task.title}`}
                                  value={task.assignee_id ?? ""}
                                  disabled={taskBusy}
                                  onChange={(event) => void updateProjectTask(
                                    task,
                                    { assignee_id: event.target.value || null },
                                  )}
                                >
                                  <option value="">Unassigned</option>
                                  {projectCollaborators.map((collaborator) => (
                                    <option key={collaborator.user_id} value={collaborator.user_id}>
                                      {collaborator.name}
                                    </option>
                                  ))}
                                </select>
                              )}
                              {canReassign && (
                                <button
                                  type="button"
                                  className="text-button danger-text"
                                  disabled={taskBusy}
                                  onClick={() => void deleteProjectTask(task)}
                                  aria-label={`Delete task ${task.title}`}
                                >
                                  Delete
                                </button>
                              )}
                            </article>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="muted compact">No team tasks yet.</p>
                    )}
                  </section>
                  <div className="annotation-library-controls">
                    <input
                      type="search"
                      value={annotationQuery}
                      onChange={(event) => setAnnotationQuery(event.target.value)}
                      placeholder="Search notes, highlights, tags, or sources…"
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
                      type="button"
                      className={`button ${pinnedAnnotationsOnly ? "primary" : "secondary"} small-button`}
                      aria-pressed={pinnedAnnotationsOnly}
                      onClick={() => setPinnedAnnotationsOnly((current) => !current)}
                    >
                      {pinnedAnnotationsOnly ? "Showing pinned" : "Pinned only"}
                    </button>
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
                      {visibleProjectAnnotations.map((annotation) => {
                        const primarySourceId = annotation.source_type === "document"
                          ? annotation.document_id
                          : annotation.paper_id;
                        const primarySourceKey = `${annotation.source_type}.${primarySourceId ?? ""}`;
                        const linkedSourceKeys = new Set(annotation.related_sources.map(
                          (source) => `${source.source_type}.${source.source_id}`,
                        ));
                        const availableSources = [
                          ...documents
                            .map((document) => ({
                              source_type: "document" as const,
                              source_id: document.document_id,
                              source_title: document.filename,
                            })),
                          ...papers
                            .map((paper) => ({
                              source_type: "paper" as const,
                              source_id: paper.paper_id,
                              source_title: paper.title,
                            })),
                        ].filter((source) =>
                          `${source.source_type}.${source.source_id}` !== primarySourceKey
                          && !linkedSourceKeys.has(`${source.source_type}.${source.source_id}`),
                        );
                        const canManage = project.access_role !== "read"
                          && (project.access_role === "owner" || annotation.author_id === user?.user_id);
                        const noteBusy = annotationBusyIds.has(annotation.annotation_id);
                        const relatedSourceTitle = (source: AnnotationSourceLink) => source.source_type === "document"
                          ? documents.find((document) => document.document_id === source.source_id)?.filename
                            ?? "Unavailable document"
                          : papers.find((paper) => paper.paper_id === source.source_id)?.title
                            ?? "Unavailable paper";
                        return (
                        <article className={`annotation-library-card${annotation.is_pinned ? " pinned" : ""}`} key={annotation.annotation_id}>
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
                              {annotation.is_pinned && <span className="annotation-pinned-badge">PINNED</span>}
                              <button type="button" onClick={() => openProjectAnnotation(annotation)}>
                                {annotation.source_title}
                              </button>
                              <button
                                type="button"
                                className="button secondary small-button"
                                onClick={() => {
                                  const sourceId = annotation.source_type === "document"
                                    ? annotation.document_id
                                    : annotation.paper_id;
                                  if (sourceId) {
                                    void summarizeProjectSource(
                                      annotation.source_type,
                                      sourceId,
                                      annotation.source_title,
                                    );
                                  }
                                }}
                                aria-label={`Summarize ${annotation.source_title} with AI`}
                              >
                                <Bot size={13} /> Summarize
                              </button>
                            </div>
                            {annotation.quote && <blockquote>{annotation.quote}</blockquote>}
                            {annotation.note && <p>{annotation.note}</p>}
                            {!!annotation.tags.length && (
                              <div className="annotation-tags" aria-label="Note tags">
                                {annotation.tags.map((tag) => <span key={tag}>{tag}</span>)}
                              </div>
                            )}
                            {!!annotation.related_sources.length && (
                              <div className="annotation-related-links" aria-label="Related sources">
                                <span>Related:</span>
                                {annotation.related_sources.map((source) => (
                                  <span className="annotation-related-link" key={`${source.source_type}.${source.source_id}`}>
                                    <button
                                      type="button"
                                      onClick={() => openProjectSource(
                                        source.source_type,
                                        source.source_id,
                                        relatedSourceTitle(source),
                                      )}
                                    >
                                      {relatedSourceTitle(source)}
                                    </button>
                                    {canManage && (
                                      <button
                                        type="button"
                                        className="annotation-unlink"
                                        disabled={noteBusy}
                                        onClick={() => void updateProjectAnnotation(annotation, {
                                          related_sources: annotation.related_sources.filter(
                                            (item) => item.source_type !== source.source_type
                                              || item.source_id !== source.source_id,
                                          ),
                                        })}
                                        aria-label={`Unlink ${relatedSourceTitle(source)}`}
                                      >
                                        ×
                                      </button>
                                    )}
                                  </span>
                                ))}
                              </div>
                            )}
                            {canManage && (
                              <div className="annotation-library-actions">
                                <button
                                  type="button"
                                  className="button secondary small-button"
                                  disabled={noteBusy}
                                  aria-pressed={annotation.is_pinned}
                                  onClick={() => void updateProjectAnnotation(annotation, {
                                    is_pinned: !annotation.is_pinned,
                                  })}
                                >
                                  {annotation.is_pinned ? "Unpin note" : "Pin note"}
                                </button>
                                <form
                                  className="annotation-tag-form"
                                  onSubmit={(event) => {
                                    event.preventDefault();
                                    const form = event.currentTarget;
                                    const formData = new FormData(form);
                                    const tags = String(formData.get("tags") ?? "")
                                      .split(",")
                                      .map((tag) => tag.trim())
                                      .filter(Boolean);
                                    void updateProjectAnnotation(annotation, { tags }).then((updated) => {
                                      const input = form.elements.namedItem("tags");
                                      if (updated && input instanceof HTMLInputElement) {
                                        input.value = updated.tags.join(", ");
                                      }
                                    });
                                  }}
                                >
                                  <input
                                    name="tags"
                                    aria-label={`Tags for note from ${annotation.source_title}`}
                                    defaultValue={annotation.tags.join(", ")}
                                    maxLength={659}
                                    placeholder="Tags, comma-separated"
                                    disabled={noteBusy}
                                  />
                                  <button className="button secondary small-button" disabled={noteBusy}>Save tags</button>
                                </form>
                                {availableSources.length > 0 && (
                                  <form
                                    className="annotation-link-form"
                                    onSubmit={(event) => {
                                      event.preventDefault();
                                      const form = event.currentTarget;
                                      const selected = String(new FormData(form).get("source") ?? "");
                                      const separator = selected.indexOf(".");
                                      if (separator < 0) return;
                                      const sourceType = selected.slice(0, separator);
                                      if (sourceType !== "document" && sourceType !== "paper") return;
                                      const sourceId = selected.slice(separator + 1);
                                      const link: AnnotationSourceLink = { source_type: sourceType, source_id: sourceId };
                                      void updateProjectAnnotation(annotation, {
                                        related_sources: [...annotation.related_sources, link],
                                      });
                                      form.reset();
                                    }}
                                  >
                                    <select name="source" defaultValue="" aria-label={`Link source to note from ${annotation.source_title}`}>
                                      <option value="" disabled>Link a paper or document</option>
                                      {availableSources.map((source) => (
                                        <option
                                          key={`${source.source_type}.${source.source_id}`}
                                          value={`${source.source_type}.${source.source_id}`}
                                        >
                                          {source.source_type === "document" ? "Document" : "Paper"}: {source.source_title}
                                        </option>
                                      ))}
                                    </select>
                                    <button className="button secondary small-button" disabled={noteBusy}>Link source</button>
                                  </form>
                                )}
                              </div>
                            )}
                            <small>Updated {new Date(annotation.updated_at).toLocaleDateString()}</small>
                          </div>
                        </article>
                        );
                      })}
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
                  {searchHistory.length > 0 && (
                    <section className="saved-searches search-records">
                      <div className="result-label">
                        <span>Search history</span>
                        <small>{searchHistory.length} records</small>
                      </div>
                      {searchHistory.map((record) => (
                        <article className="saved-search-row" key={record.query_id}>
                          <div className="saved-search-copy">
                            <strong>{record.query_text}</strong>
                            <small>
                              {record.api_provider === "openalex" ? "OpenAlex" : "Crossref"} · {new Date(record.searched_at).toLocaleString()} · {record.result_count} results
                            </small>
                            <small>
                              Filters: {Object.entries(record.search_filters)
                                .map(([name, value]) => name === "limit"
                                  ? `Maximum results: ${value}`
                                  : `${name}: ${value}`)
                                .join(" · ") || "Not recorded for this entry"}
                            </small>
                          </div>
                          <button
                            className="button secondary small-button"
                            disabled={busy}
                            onClick={() => void rerunSearchHistory(record)}
                          >
                            {busy ? "Searching…" : "Rerun"}
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
                      <div className="result-label"><span>Search results</span><small>{searchResults.result_count} papers · {searchResults.provider}</small></div>
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
                          alreadySaved={paper.saved}
                          onSave={() => reviewPaperBeforeSave(paper)}
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
                    <StudyExtractionTable
                      key={project.project_id}
                      papers={papers}
                      canEdit={canEditProject}
                      onSave={savePaperStudyExtraction}
                    />
                    <section className="screening-progress" aria-label="Literature screening progress">
                      <div className="screening-progress-heading">
                        <strong>Screening progress</strong>
                        <span>
                          {reviewedPaperCount} of {papers.length} adjudicated · {reviewerAssessmentCount} reviewer assessments
                        </span>
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
                        <span>{screeningDisagreementCount} disagreements</span>
                      </div>
                    </section>
                    <section className="screening-assignee-progress" aria-label="Screening progress by reviewer">
                      <div className="screening-progress-heading">
                        <strong>Reviewer assignments</strong>
                        <span>{unassignedScreeningPaperCount} papers unassigned</span>
                      </div>
                      {screeningAssignmentProgress.length ? (
                        <div className="screening-assignee-list">
                          {screeningAssignmentProgress.map((reviewer) => (
                            <div className="screening-assignee-row" key={reviewer.userId}>
                              <div className="screening-assignee-heading">
                                <strong>{reviewer.userName}</strong>
                                {!reviewer.eligible && <span>Access changed</span>}
                                <small>
                                  {reviewer.completedCount} of {reviewer.assignedCount} assigned papers screened
                                </small>
                              </div>
                              <progress
                                max={Math.max(reviewer.assignedCount, 1)}
                                value={reviewer.completedCount}
                                aria-label={`${reviewer.userName}: ${reviewer.completedCount} of ${reviewer.assignedCount} assigned papers screened`}
                              />
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="muted compact">No reviewers with commenting or editing access.</p>
                      )}
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
                          <LibraryMetadataFilters
                            kind="papers"
                            filters={paperMetadataFilters}
                            onChange={setPaperMetadataFilters}
                          />
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
                              Set project adjudication to
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
                            {bulkScreeningStatus === "exclude" && (
                              <>
                                <label>
                                  Exclusion reason
                                  <select
                                    value={bulkExclusionReason}
                                    onChange={(event) =>
                                      setBulkExclusionReason(event.target.value as ScreeningExclusionReason | "")
                                    }
                                    disabled={!canEditProject || screeningBusy}
                                  >
                                    <option value="">Choose a reason</option>
                                    {SCREENING_EXCLUSION_REASONS.map((reason) => (
                                      <option key={reason.value} value={reason.value}>{reason.label}</option>
                                    ))}
                                  </select>
                                </label>
                                {bulkExclusionReason === "other" && (
                                  <label>
                                    Explain “Other”
                                    <input
                                      value={bulkScreeningNote}
                                      onChange={(event) => setBulkScreeningNote(event.target.value)}
                                      maxLength={500}
                                      placeholder="Required for Other"
                                      disabled={!canEditProject || screeningBusy}
                                    />
                                  </label>
                                )}
                              </>
                            )}
                            <button
                              className="button primary small-button"
                              onClick={() => void bulkUpdatePaperScreening()}
                              disabled={!canEditProject || screeningBusy ||
                                bulkScreeningStatus === "exclude" && !bulkExclusionReason ||
                                bulkScreeningStatus === "exclude" && bulkExclusionReason === "other" &&
                                !bulkScreeningNote.trim()
                              }
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
                            ? (status, note, reason) => void updatePaperScreening(paper, status, note, reason)
                            : undefined}
                          currentUserId={user?.user_id ?? null}
                          onReviewerDecisionChange={canEditProject
                            || canCommentOnProject && paper.screening_assignments.some(
                              (assignment) => assignment.user_id === user?.user_id,
                            )
                            ? (status, reason, note) =>
                              updateReviewerScreeningDecision(paper, status, reason, note)
                            : undefined}
                          collaborators={projectCollaborators}
                          onScreeningAssignmentsChange={canEditProject
                            ? (userIds) => updatePaperScreeningAssignments(paper, userIds)
                            : undefined}
                          onMetadataChange={canEditProject
                            ? (tags, metadata) => updatePaperMetadata(paper, tags, metadata)
                            : undefined}
                          onRemove={canEditProject ? () => void unsavePaper(paper) : undefined}
                          onAnnotate={() => {
                            if (annotationPaperId !== paper.paper_id) {
                              rememberRecentProjectSource(
                                project.project_id,
                                "paper",
                                paper.paper_id,
                                paper.title,
                              );
                            }
                            setAnnotationPaperId((current) =>
                              current === paper.paper_id ? null : paper.paper_id
                            );
                          }}
                          onSummarize={() => void summarizeProjectSource("paper", paper.paper_id, paper.title)}
                          onImportFullText={canEditProject ? () => void importPaperFullText(paper) : undefined}
                          importingFullText={busy}
                        />
                        {annotationPaperId === paper.paper_id && (
                          <AnnotationEditor
                            key={`annotations-${paper.paper_id}`}
                            projectId={project.project_id}
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

              {view === "collections" && (
                <ProjectCollections
                  projectId={project.project_id}
                  documents={documents}
                  papers={papers}
                  canEdit={Boolean(canEditProject)}
                  request={request}
                  onOpenSource={openProjectSource}
                />
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
                      {conversation?.messages?.map((message, messageIndex) => (
                        <div className={`message ${message.role}`} key={message.message_id}>
                          <div className="message-label">{message.role === "assistant" ? "FIELDNOTES" : "YOU"}</div>
                          <AnswerContent content={message.content} sources={message.sources} onSourceClick={(source) => openSource(source, `source-${message.message_id}-${message.sources.indexOf(source)}`)} />
                          {message.role === "assistant" && (
                            <>
                              {!!message.sources.length && (
                                <AssistantSourceCards
                                  idPrefix={`source-${message.message_id}`}
                                  label="CITED SOURCES"
                                  sources={message.sources}
                                  onOpen={openSource}
                                  onRevise={(source) => reviseWithoutSource(source, conversation.messages?.slice(0, messageIndex).reverse().find((item) => item.role === "user")?.content ?? "")}
                                />
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
                          <AnswerContent content={draft.answer} sources={draft.sources} onSourceClick={(source) => openSource(source, `source-draft-${draft.sources.indexOf(source)}`)} />
                          {!!draft.sources.length && (
                            <AssistantSourceCards
                              key={draft.approval_token}
                              idPrefix="source-draft"
                              label="SOURCES TO REVIEW"
                              sources={draft.sources}
                              onOpen={openSource}
                              onRevise={(source) => reviseWithoutSource(source, draftQuestion)}
                            />
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
                      <details className="assistant-source-picker">
                        <summary>{assistantSources ? `Selected sources (${assistantSources.document_ids.length + assistantSources.paper_ids.length})` : "Sources: automatic"}</summary>
                        <label>
                          <input type="checkbox" checked={assistantSources !== null} onChange={(event) => setAssistantSources(event.target.checked ? allAssistantSources(documents, papers) : null)} />
                          Choose project sources for this question
                        </label>
                        {assistantSources && (
                          <div className="assistant-source-options">
                            <p>Only checked sources will be used. External paper discovery is off.</p>
                            {documents.filter((document) => document.processing_status === "ready").map((document) => (
                              <label key={document.document_id}>
                                <input type="checkbox" checked={assistantSources.document_ids.includes(document.document_id)} onChange={(event) => {
                                  const ids = assistantSources.document_ids.filter((id) => id !== document.document_id);
                                  setAssistantSources({ ...assistantSources, document_ids: event.target.checked ? [...ids, document.document_id] : ids });
                                }} />
                                Document: {document.filename}
                              </label>
                            ))}
                            {papers.map((paper) => (
                              <label key={paper.paper_id}>
                                <input type="checkbox" checked={assistantSources.paper_ids.includes(paper.paper_id)} onChange={(event) => {
                                  const ids = assistantSources.paper_ids.filter((id) => id !== paper.paper_id);
                                  setAssistantSources({ ...assistantSources, paper_ids: event.target.checked ? [...ids, paper.paper_id] : ids });
                                }} />
                                Paper: {paper.title}
                              </label>
                            ))}
                            {!documents.some((document) => document.processing_status === "ready") && !papers.length && <p>No ready documents or saved papers are available.</p>}
                          </div>
                        )}
                      </details>
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

function AssistantSourceCards({
  idPrefix,
  label,
  sources,
  onOpen,
  onRevise,
}: {
  idPrefix: string;
  label: string;
  sources: Source[];
  onOpen: (source: Source, cardId: string) => void;
  onRevise: (source: Source) => void;
}) {
  const [flagged, setFlagged] = useState<Set<number>>(() => new Set());
  return (
    <div className="source-list">
      <span className="source-list-label">{label} · Flags are temporary</span>
      {sources.map((source, index) => {
        const cardId = `${idPrefix}-${index}`;
        return (
          <article className="source-card" key={`${source.kind}-${source.source_id}-${index}`} id={cardId} tabIndex={-1}>
            <span className="source-index">S{index + 1}</span>
            <div className="source-card-content">
              <strong>{source.title}</strong>
              {source.page_number && <span className="source-page">PDF · page {source.page_number}</span>}
              <p>{source.excerpt}</p>
              {source.kind === "document" && source.document_id && (
                <button type="button" className="source-open-button" onClick={() => onOpen(source, cardId)}>
                  {source.page_number ? `Open page ${source.page_number}` : "Open passage"}
                </button>
              )}
              {source.kind === "paper" && source.paper_url && (
                <a className="source-open-button" href={source.paper_url} target="_blank" rel="noreferrer">Open paper <ArrowUpRight size={12} /></a>
              )}
              <div className="source-review-actions">
                <button type="button" aria-pressed={flagged.has(index)} onClick={() => setFlagged((current) => {
                  const next = new Set(current);
                  if (next.has(index)) next.delete(index);
                  else next.add(index);
                  return next;
                })}>{flagged.has(index) ? "Flagged weak" : "Flag weak"}</button>
                <button type="button" onClick={() => onRevise(source)}>Revise without this source</button>
              </div>
            </div>
          </article>
        );
      })}
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

function TabButton({
  active,
  onClick,
  icon,
  children,
  shortcut,
  ariaKeyShortcuts,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
  shortcut?: string;
  ariaKeyShortcuts?: string;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      className={`tab-button ${active ? "active" : ""}`}
      aria-keyshortcuts={ariaKeyShortcuts}
      title={shortcut ? `Shortcut: ${shortcut}` : undefined}
      onClick={onClick}
    >
      {icon}{children}
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
  alreadySaved = false,
  canEditProject,
  canCommentOnProject,
  onSave,
  onRemove,
  onAnnotate,
  onSummarize,
  onScreeningChange,
  currentUserId,
  onReviewerDecisionChange,
  collaborators = [],
  onScreeningAssignmentsChange,
  onMetadataChange,
  selected = false,
  onSelectionChange,
  onImportFullText,
  importingFullText,
}: {
  paper: Paper;
  saved?: boolean;
  alreadySaved?: boolean;
  canEditProject: boolean;
  canCommentOnProject: boolean;
  onSave?: () => void;
  onRemove?: () => void;
  onAnnotate?: () => void;
  onSummarize?: () => void;
  onScreeningChange?: (
    status: Paper["screening_status"],
    note: string,
    reason: ScreeningExclusionReason | null,
  ) => void;
  currentUserId?: string | null;
  onReviewerDecisionChange?: (
    status: PaperScreeningDecision["screening_status"],
    reason: ScreeningExclusionReason | null,
    note: string,
  ) => Promise<PaperScreeningDecision>;
  collaborators?: ProjectCollaborator[];
  onScreeningAssignmentsChange?: (userIds: string[]) => Promise<PaperScreeningAssignment[]>;
  onMetadataChange?: (tags: string[], metadata: Record<string, string>) => Promise<void>;
  selected?: boolean;
  onSelectionChange?: (selected: boolean) => void;
  onImportFullText?: () => void;
  importingFullText?: boolean;
}) {
  const [screeningStatus, setScreeningStatus] = useState(paper.screening_status);
  const [screeningNote, setScreeningNote] = useState(paper.screening_note);
  const [screeningReason, setScreeningReason] = useState<ScreeningExclusionReason | "">(
    paper.screening_exclusion_reason ?? "",
  );
  const [reviewerStatus, setReviewerStatus] = useState<PaperScreeningDecision["screening_status"] | "">("");
  const [reviewerReason, setReviewerReason] = useState<ScreeningExclusionReason | "">("");
  const [reviewerNote, setReviewerNote] = useState("");
  const [reviewerDirty, setReviewerDirty] = useState(false);
  const [reviewerSaving, setReviewerSaving] = useState(false);
  const [reviewerError, setReviewerError] = useState("");
  const [assignmentIds, setAssignmentIds] = useState(
    paper.screening_assignments.map((assignment) => assignment.user_id),
  );
  const [assignmentSaving, setAssignmentSaving] = useState(false);
  const [assignmentError, setAssignmentError] = useState("");
  const myDecision = paper.screening_decisions.find((decision) => decision.user_id === currentUserId);
  const assignmentOptions = useMemo(() => {
    const options = collaborators.filter((collaborator) => collaborator.role !== "read");
    const optionIds = new Set(options.map((collaborator) => collaborator.user_id));
    for (const assignment of paper.screening_assignments) {
      if (optionIds.has(assignment.user_id)) continue;
      const currentCollaborator = collaborators.find(
        (collaborator) => collaborator.user_id === assignment.user_id,
      );
      options.push({
        user_id: assignment.user_id,
        username: assignment.username ?? "",
        name: currentCollaborator?.name ?? assignment.user_name,
        role: "read",
      });
    }
    return options;
  }, [collaborators, paper.screening_assignments]);
  const currentAssignmentIds = paper.screening_assignments
    .map((assignment) => assignment.user_id)
    .sort();
  const selectedAssignmentIds = [...assignmentIds].sort();
  const assignmentSelectionChanged = currentAssignmentIds.length !== selectedAssignmentIds.length
    || currentAssignmentIds.some((userId, index) => userId !== selectedAssignmentIds[index]);

  useEffect(() => {
    setScreeningStatus(paper.screening_status);
    setScreeningNote(paper.screening_note);
    setScreeningReason(paper.screening_exclusion_reason ?? "");
  }, [paper.screening_status, paper.screening_note, paper.screening_exclusion_reason]);

  useEffect(() => {
    setAssignmentIds(paper.screening_assignments.map((assignment) => assignment.user_id));
  }, [paper.screening_assignments]);

  useEffect(() => {
    if (reviewerDirty) return;
    setReviewerStatus(myDecision?.screening_status ?? "");
    setReviewerReason(myDecision?.exclusion_reason ?? "");
    setReviewerNote(myDecision?.screening_note ?? "");
  }, [
    currentUserId,
    myDecision?.screening_note,
    myDecision?.screening_status,
    myDecision?.exclusion_reason,
    reviewerDirty,
  ]);

  async function saveReviewerDecision() {
    if (!onReviewerDecisionChange || !reviewerStatus) return;
    const reason = reviewerStatus === "exclude" && reviewerReason ? reviewerReason : null;
    if (reviewerStatus === "exclude" && !reason) {
      setReviewerError("Choose a structured exclusion reason.");
      return;
    }
    if (reason === "other" && !reviewerNote.trim()) {
      setReviewerError("Add a note when the exclusion reason is Other.");
      return;
    }
    setReviewerSaving(true);
    setReviewerError("");
    try {
      const savedDecision = await onReviewerDecisionChange(reviewerStatus, reason, reviewerNote.trim());
      setReviewerStatus(savedDecision.screening_status);
      setReviewerReason(savedDecision.exclusion_reason ?? "");
      setReviewerNote(savedDecision.screening_note);
      setReviewerDirty(false);
    } catch (cause) {
      setReviewerError(cause instanceof Error ? cause.message : "Could not save your decision.");
    } finally {
      setReviewerSaving(false);
    }
  }

  async function saveScreeningAssignments() {
    if (!onScreeningAssignmentsChange) return;
    setAssignmentSaving(true);
    setAssignmentError("");
    try {
      await onScreeningAssignmentsChange(assignmentIds);
    } catch (cause) {
      setAssignmentError(cause instanceof Error ? cause.message : "Could not save reviewer assignments.");
    } finally {
      setAssignmentSaving(false);
    }
  }

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
        {paper.screening_disagreement && (
          <span className="screening-disagreement" role="status">Reviewer disagreement</span>
        )}
        <h3>{paper.title}</h3>
        <p className="paper-meta">
          {[paper.authors.slice(0, 4).map((author) => author.author_name).join(", "), paper.publication_year, paper.venue, paper.citation_count != null ? `${paper.citation_count.toLocaleString()} citations` : ""].filter(Boolean).join(" · ") || paper.api_provider}
        </p>
        {paper.abstract && <p className="paper-abstract">{paper.abstract.replace(/<[^>]*>/g, "").slice(0, 500)}{paper.abstract.length > 500 ? "…" : ""}</p>}
        {paper.doi && <p className="doi-line">DOI: {paper.doi.replace(/^https?:\/\/doi\.org\//, "")}</p>}
        {saved && (
          <div className="screening-review-workspace">
            <section className="screening-review-panel" aria-label="Project adjudication">
              <strong>Project adjudication</strong>
              <div className="screening-controls">
                <label>
                  Final decision
                  <select
                    value={screeningStatus}
                    onChange={(event) => setScreeningStatus(event.target.value as Paper["screening_status"])}
                    aria-label={`Project adjudication for ${paper.title}`}
                    disabled={!canEditProject}
                  >
                    <option value="unread">Unread</option>
                    <option value="undecided">Undecided</option>
                    <option value="include">Include</option>
                    <option value="exclude">Exclude</option>
                  </select>
                </label>
                {screeningStatus === "exclude" && (
                  <label>
                    Exclusion reason
                    <select
                      value={screeningReason}
                      onChange={(event) =>
                        setScreeningReason(event.target.value as ScreeningExclusionReason | "")
                      }
                      disabled={!canEditProject}
                    >
                      <option value="">Choose a reason</option>
                      {SCREENING_EXCLUSION_REASONS.map((reason) => (
                        <option key={reason.value} value={reason.value}>{reason.label}</option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  Adjudication note
                  <input
                    value={screeningNote}
                    onChange={(event) => setScreeningNote(event.target.value)}
                    maxLength={500}
                    placeholder="Optional note"
                    aria-label={`Adjudication note for ${paper.title}`}
                    disabled={!canEditProject}
                  />
                </label>
                <button
                  className="button secondary small-button"
                  onClick={() => onScreeningChange?.(
                    screeningStatus,
                    screeningNote,
                    screeningStatus === "exclude" && screeningReason ? screeningReason : null,
                  )}
                  disabled={!onScreeningChange ||
                    screeningStatus === "exclude" && !screeningReason ||
                    screeningStatus === "exclude" && screeningReason === "other" && !screeningNote.trim() ||
                    screeningStatus === paper.screening_status &&
                    screeningNote === paper.screening_note &&
                    (screeningStatus !== "exclude" || screeningReason === (paper.screening_exclusion_reason ?? ""))
                  }
                >
                  Save adjudication
                </button>
              </div>
            </section>
            <section className="screening-review-panel screening-assignment-panel" aria-label="Paper review assignments">
              <strong>Review assignments</strong>
              {paper.screening_assignments.length ? (
                <ul className="screening-assignment-status">
                  {paper.screening_assignments.map((assignment) => {
                    const decision = paper.screening_decisions.find(
                      (item) => item.user_id === assignment.user_id,
                    );
                    return (
                      <li key={assignment.user_id}>
                        <span>{assignment.user_name}</span>
                        <span>{decision ? `Screened · ${decision.screening_status}` : "Not screened"}</span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted compact">No reviewers assigned.</p>
              )}
              {onScreeningAssignmentsChange && (
                <details className="screening-assignment-editor">
                  <summary>Manage reviewers</summary>
                  <div className="screening-assignment-options">
                    {assignmentOptions.length ? assignmentOptions.map((collaborator) => (
                      <label key={collaborator.user_id}>
                        <input
                          type="checkbox"
                          checked={assignmentIds.includes(collaborator.user_id)}
                          onChange={(event) => {
                            setAssignmentIds((current) => event.target.checked
                              ? [...current, collaborator.user_id]
                              : current.filter((id) => id !== collaborator.user_id));
                          }}
                          disabled={assignmentSaving}
                        />
                        <span>{collaborator.name}</span>
                        {collaborator.role === "read" && <small>Access changed</small>}
                      </label>
                    )) : (
                      <span className="muted compact">No eligible project collaborators.</span>
                    )}
                  </div>
                  <button
                    className="button secondary small-button"
                    onClick={() => void saveScreeningAssignments()}
                    disabled={assignmentSaving || !assignmentSelectionChanged}
                  >
                    {assignmentSaving ? "Saving…" : "Save reviewers"}
                  </button>
                  {assignmentError && <p className="screening-form-error" role="alert">{assignmentError}</p>}
                </details>
              )}
              {!canEditProject && canCommentOnProject &&
                !paper.screening_assignments.some((assignment) => assignment.user_id === currentUserId) && (
                  <p className="muted compact">An editor must assign you before you can submit an assessment.</p>
                )}
            </section>
            <section className="screening-review-panel reviewer-decision-panel" aria-label="Independent reviewer assessment">
              <div className="reviewer-decision-heading">
                <strong>Your independent assessment</strong>
                {myDecision && (
                  <span>Last saved {new Date(myDecision.updated_at).toLocaleString()}</span>
                )}
              </div>
              <div className="screening-controls">
                <label>
                  Your decision
                  <select
                    value={reviewerStatus}
                    onChange={(event) => {
                      setReviewerStatus(event.target.value as PaperScreeningDecision["screening_status"] | "");
                      setReviewerDirty(true);
                    }}
                    disabled={!onReviewerDecisionChange || reviewerSaving}
                  >
                    <option value="" disabled={Boolean(myDecision)}>Not screened</option>
                    <option value="undecided">Undecided</option>
                    <option value="include">Include</option>
                    <option value="exclude">Exclude</option>
                  </select>
                </label>
                {reviewerStatus === "exclude" && (
                  <label>
                    Exclusion reason
                    <select
                      value={reviewerReason}
                      onChange={(event) => {
                        setReviewerReason(event.target.value as ScreeningExclusionReason | "");
                        setReviewerDirty(true);
                      }}
                      disabled={!onReviewerDecisionChange || reviewerSaving}
                    >
                      <option value="">Choose a reason</option>
                      {SCREENING_EXCLUSION_REASONS.map((reason) => (
                        <option key={reason.value} value={reason.value}>{reason.label}</option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  Reviewer note
                  <input
                    value={reviewerNote}
                    onChange={(event) => {
                      setReviewerNote(event.target.value);
                      setReviewerDirty(true);
                    }}
                    maxLength={500}
                    placeholder="Optional note"
                    disabled={!onReviewerDecisionChange || reviewerSaving}
                  />
                </label>
                <button
                  className="button secondary small-button"
                  onClick={() => void saveReviewerDecision()}
                  disabled={!onReviewerDecisionChange || reviewerSaving || !reviewerStatus ||
                    reviewerStatus === "exclude" && !reviewerReason ||
                    reviewerStatus === "exclude" && reviewerReason === "other" &&
                    !reviewerNote.trim() ||
                    !reviewerDirty
                  }
                >
                  {reviewerSaving ? "Saving…" : "Save my assessment"}
                </button>
              </div>
              {reviewerError && <p className="screening-form-error" role="alert">{reviewerError}</p>}
              {paper.screening_decisions.length > 0 && (
                <ul className="reviewer-decision-trail" aria-label="Reviewer decision trail">
                  {paper.screening_decisions.map((decision) => (
                    <li key={decision.user_id}>
                      <span>
                        <strong>{decision.user_name}</strong>: {decision.screening_status}
                        {decision.exclusion_reason && (
                          <> · {SCREENING_EXCLUSION_REASONS.find(
                            (reason) => reason.value === decision.exclusion_reason,
                          )?.label ?? decision.exclusion_reason}</>
                        )}
                        {decision.screening_note && <> · {decision.screening_note}</>}
                      </span>
                      <time dateTime={decision.updated_at}>
                        {new Date(decision.updated_at).toLocaleString()}
                      </time>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
        {saved && (
          <LibraryMetadataEditor
            tags={paper.tags}
            metadata={paper.metadata}
            canEdit={canEditProject}
            onSave={onMetadataChange}
          />
        )}
      </div>
      <div className="paper-actions">
        {paper.paper_url && <a className="icon-button" href={paper.paper_url} target="_blank" rel="noreferrer" title="Open paper"><ArrowUpRight size={16} /></a>}
        {saved ? (
          <>
            {onSummarize && (
              <button
                className="button secondary small-button"
                onClick={onSummarize}
                aria-label={`Summarize ${paper.title} with AI`}
              >
                <Bot size={13} /> Summarize
              </button>
            )}
            <button className="button secondary small-button" onClick={onAnnotate} disabled={!canCommentOnProject}><Pencil size={13} /> Comment</button>
            <button className="button secondary small-button" onClick={onImportFullText} disabled={!canEditProject || importingFullText}>
              {importingFullText ? <LoaderCircle size={13} className="spin" /> : <FileText size={13} />}
              {importingFullText ? "Importing…" : "Extract full text"}
            </button>
            {onRemove && <button className="button secondary small-button" onClick={onRemove}><X size={14} /> Remove</button>}
          </>
        ) : (
          <button
            className="button secondary small-button"
            onClick={onSave}
            disabled={!canEditProject || alreadySaved}
          >
            {alreadySaved ? <Check size={15} /> : <Plus size={15} />}
            {alreadySaved ? "Saved" : "Save"}
          </button>
        )}
      </div>
    </article>
  );
}

function LibraryMetadataFilters({
  kind,
  filters,
  onChange,
}: {
  kind: "documents" | "papers";
  filters: LibraryMetadataFilters;
  onChange: (filters: LibraryMetadataFilters) => void;
}) {
  const update = (field: keyof LibraryMetadataFilters, value: string) => {
    onChange({ ...filters, [field]: value });
  };
  return (
    <div className="library-metadata-filters" aria-label={`${kind} tag and metadata filters`}>
      <label>
        Filter {kind} by tag
        <input
          value={filters.tag}
          onChange={(event) => update("tag", event.target.value)}
          placeholder="e.g. methods"
        />
      </label>
      <label>
        Metadata field
        <input
          value={filters.metadataKey}
          onChange={(event) => update("metadataKey", event.target.value)}
          placeholder="e.g. study design"
        />
      </label>
      <label>
        Metadata value
        <input
          value={filters.metadataValue}
          onChange={(event) => update("metadataValue", event.target.value)}
          placeholder="Filter by value"
        />
      </label>
    </div>
  );
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return typeof value === "object"
    && value !== null
    && !Array.isArray(value)
    && Object.values(value).every((item) => typeof item === "string");
}

function LibraryMetadataEditor({
  tags,
  metadata,
  canEdit,
  onSave,
}: {
  tags: string[];
  metadata: Record<string, string>;
  canEdit: boolean;
  onSave?: (tags: string[], metadata: Record<string, string>) => Promise<void>;
}) {
  const [tagText, setTagText] = useState(tags.join("\n"));
  const [metadataText, setMetadataText] = useState(JSON.stringify(metadata, null, 2));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (dirty) return;
    setTagText(tags.join("\n"));
    setMetadataText(JSON.stringify(metadata, null, 2));
  }, [dirty, metadata, tags]);

  async function saveMetadata() {
    if (!onSave) return;
    setError("");
    let parsed: unknown;
    try {
      parsed = JSON.parse(metadataText);
    } catch {
      setError("Metadata must be a valid JSON object of string values.");
      return;
    }
    if (!isStringRecord(parsed)) {
      setError("Metadata must be a JSON object with string values.");
      return;
    }
    setSaving(true);
    try {
      await onSave(
        tagText.split(/\r?\n/).map((tag) => tag.trim()).filter(Boolean),
        parsed,
      );
      setDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save tags and metadata.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="library-metadata">
      <div className="library-metadata-summary">
        {tags.map((tag) => <span className="library-tag" key={tag}>{tag}</span>)}
        {Object.entries(metadata).map(([key, value]) => (
          <span className="library-meta-entry" key={key}><strong>{key}:</strong> {value}</span>
        ))}
        {!tags.length && !Object.keys(metadata).length && (
          <span className="muted">No tags or metadata</span>
        )}
      </div>
      {canEdit && (
        <details className="library-metadata-editor">
          <summary>Edit tags and metadata</summary>
          <label>
            Tags (one per line)
            <textarea
              value={tagText}
              onChange={(event) => {
                setTagText(event.target.value);
                setDirty(true);
              }}
              maxLength={2_000}
              rows={2}
              placeholder={"methods\npriority"}
            />
          </label>
          <label>
            Custom metadata (JSON object with string values)
            <textarea
              value={metadataText}
              onChange={(event) => {
                setMetadataText(event.target.value);
                setDirty(true);
              }}
              rows={3}
              maxLength={20_000}
              placeholder={'{\n  "study design": "randomized trial"\n}'}
              spellCheck={false}
            />
          </label>
          {error && <span className="inline-error" role="alert">{error}</span>}
          <button
            className="button secondary small-button"
            type="button"
            onClick={() => void saveMetadata()}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save tags and metadata"}
          </button>
        </details>
      )}
    </div>
  );
}

function MentionableTextarea({
  value,
  onChange,
  collaborators,
  currentUserId,
  ...textareaProps
}: Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange"> & {
  value: string;
  onChange: (value: string) => void;
  collaborators: ProjectCollaborator[];
  currentUserId: string | null;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [mentionQuery, setMentionQuery] = useState<ReturnType<typeof getMentionQuery>>(null);
  const suggestions = mentionQuery
    ? collaborators
      .filter((collaborator) =>
        collaborator.user_id !== currentUserId
        && collaborator.username.toLocaleLowerCase().startsWith(mentionQuery.query.toLocaleLowerCase()),
      )
      .slice(0, 6)
    : [];

  function updateQuery(textarea: HTMLTextAreaElement) {
    setMentionQuery(getMentionQuery(textarea.value, textarea.selectionStart));
  }

  function chooseMention(username: string) {
    if (!mentionQuery) return;
    const result = insertMention(value, mentionQuery.end, username);
    onChange(result.value);
    setMentionQuery(null);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(result.cursor, result.cursor);
    });
  }

  return (
    <div className="mentionable-textarea">
      <textarea
        {...textareaProps}
        ref={textareaRef}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          updateQuery(event.currentTarget);
        }}
        onSelect={(event) => updateQuery(event.currentTarget)}
        onKeyUp={(event) => updateQuery(event.currentTarget)}
        onBlur={() => setMentionQuery(null)}
      />
      {suggestions.length > 0 && (
        <div className="mention-suggestions" role="listbox" aria-label="Project collaborator suggestions">
          {suggestions.map((collaborator) => (
            <button
              type="button"
              role="option"
              aria-selected="false"
              key={collaborator.user_id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => chooseMention(collaborator.username)}
            >
              <strong>@{collaborator.username}</strong><span>{collaborator.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AnnotationEditor({
  projectId,
  annotationsPath,
  sourcePath,
  sourceText,
  sourceStatus,
  citationExcerpt,
  canComment,
  currentUserId,
  isProjectOwner,
}: {
  projectId: string;
  annotationsPath: string;
  sourcePath?: string;
  sourceText?: string;
  sourceStatus?: string;
  citationExcerpt?: string | null;
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
  const [collaborators, setCollaborators] = useState<ProjectCollaborator[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sourceRef = useRef<HTMLDivElement>(null);
  const citationHighlightRef = useRef<HTMLElement>(null);

  useEffect(() => {
    let active = true;
    api<ProjectCollaborator[]>(`/api/projects/${projectId}/collaborators`)
      .then((loaded) => {
        if (active) setCollaborators(loaded);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load project collaborators.");
      });
    return () => {
      active = false;
    };
  }, [projectId]);

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

  const citationRange = findCitationRange(text, citationExcerpt ?? null);

  useEffect(() => {
    if (loading || !citationRange) return;
    citationHighlightRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [citationRange?.start, citationRange?.end, loading]);

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
  const highlightRanges: { start: number; end: number; annotationId: string }[] = [];
  let highlightCursor = 0;
  validHighlights.forEach((item) => {
    const start = item.start_offset ?? 0;
    const end = item.end_offset ?? start;
    if (start < highlightCursor || end > sourceCharacters.length) return;
    highlightRanges.push({ start, end, annotationId: item.annotation_id });
    highlightCursor = end;
  });
  const sourceParts: ReactNode[] = [];
  const boundaries = new Set([0, sourceCharacters.length]);
  highlightRanges.forEach(({ start, end }) => {
    boundaries.add(start);
    boundaries.add(end);
  });
  if (citationRange) {
    boundaries.add(citationRange.start);
    boundaries.add(citationRange.end);
  }
  const orderedBoundaries = [...boundaries].sort((left, right) => left - right);
  orderedBoundaries.slice(0, -1).forEach((start, index) => {
    const end = orderedBoundaries[index + 1];
    if (start === end) return;
    const annotation = highlightRanges.find((range) => range.start <= start && end <= range.end);
    const isCitation = Boolean(citationRange && citationRange.start <= start && end <= citationRange.end);
    const content = sourceCharacters.slice(start, end).join("");
    if (!annotation && !isCitation) {
      sourceParts.push(content);
      return;
    }
    sourceParts.push(
      <mark
        key={`${annotation?.annotationId ?? "citation"}-${start}`}
        className={isCitation ? "citation-passage" : undefined}
        ref={isCitation ? citationHighlightRef : undefined}
      >
        {content}
      </mark>,
    );
  });

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
            <MentionableTextarea
              id={`annotation-note-${annotationsPath}`}
              value={note}
              onChange={setNote}
              placeholder="What stands out about this passage?"
              maxLength={5000}
              rows={3}
              collaborators={collaborators}
              currentUserId={currentUserId}
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
                      <MentionableTextarea
                        value={editNote}
                        onChange={setEditNote}
                        maxLength={5000}
                        rows={2}
                        collaborators={collaborators}
                        currentUserId={currentUserId}
                        aria-label="Edit annotation note"
                      />
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
