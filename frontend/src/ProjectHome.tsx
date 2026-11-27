import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  Clock3,
  FileText,
  Library,
  ListTodo,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useEffect, useState } from "react";
import type {
  DocumentRecord,
  ProjectActivity,
  ProjectTask,
  RecentProjectSource,
} from "./types";

type Props = {
  projectId: string;
  documents: DocumentRecord[];
  recentSources: RecentProjectSource[];
  recentSourcesError: string;
  request: <T,>(path: string, options?: RequestInit) => Promise<T>;
  onOpenSource: (
    sourceType: "document" | "paper",
    sourceId: string,
    sourceTitle: string,
  ) => void;
};

const ACTIVITY_LABELS: Record<string, string> = {
  "project.created": "Project created",
  "project.updated": "Project details updated",
  "document.uploaded": "Document uploaded",
  "document.metadata.updated": "Document details updated",
  "document.reprocessed": "Document reprocessing started",
  "document.deleted": "Document removed",
  "paper.references_imported": "References imported",
  "paper.saved": "Paper saved",
  "paper.removed": "Paper removed",
  "paper.full_text.imported": "Paper full text imported",
  "paper.metadata.updated": "Paper details updated",
  "paper.screening.updated": "Paper screening updated",
  "paper.screening.decision.updated": "Reviewer decision updated",
  "paper.screening.bulk_updated": "Screening decisions updated",
  "systematic_review.saved": "Review protocol updated",
  "annotation.created": "Note added",
  "annotation.updated": "Note updated",
  "annotation.deleted": "Note removed",
  "project_task.created": "Task assigned",
  "project_task.updated": "Task updated",
  "project_task.deleted": "Task removed",
  "project_collection.created": "Collection created",
  "project_collection.renamed": "Collection renamed",
  "project_collection.deleted": "Collection deleted",
  "project_collection.source_added": "Source added to a collection",
  "project_collection.source_removed": "Source removed from a collection",
  "latex_workspace.saved": "LaTeX workspace saved",
  "latex_workspace.version_restored": "LaTeX version restored",
  "python_workspace.saved": "Python workspace saved",
  "python_workspace.version_restored": "Python version restored",
  "python_workspace.outputs_saved": "Python output saved",
  "python_workspace.output_deleted": "Python output removed",
};

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Could not load project home.";
}

function activityLabel(action: string): string {
  return ACTIVITY_LABELS[action] ?? action.replace(/[._]/g, " ");
}

function taskStatusLabel(status: ProjectTask["status"]): string {
  return status === "in_progress" ? "In progress" : "Open";
}

export function ProjectHome({
  projectId,
  documents,
  recentSources,
  recentSourcesError,
  request,
  onOpenSource,
}: Props) {
  const [activity, setActivity] = useState<ProjectActivity[]>([]);
  const [tasks, setTasks] = useState<ProjectTask[]>([]);
  const [activityError, setActivityError] = useState("");
  const [tasksError, setTasksError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setActivityError("");
    setTasksError("");
    Promise.allSettled([
      request<ProjectActivity[]>(`/api/projects/${projectId}/home/activity`),
      request<ProjectTask[]>(`/api/projects/${projectId}/tasks`),
    ]).then(([activityResult, taskResult]) => {
      if (!active) return;
      if (activityResult.status === "fulfilled") {
        setActivity(activityResult.value);
      } else {
        setActivityError(errorMessage(activityResult.reason));
      }
      if (taskResult.status === "fulfilled") {
        setTasks(taskResult.value);
      } else {
        setTasksError(errorMessage(taskResult.reason));
      }
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [projectId, reloadKey, request]);

  const processingDocuments = documents
    .filter((document) => document.processing_status !== "ready")
    .sort((left, right) => {
      const priority = (status: DocumentRecord["processing_status"]) =>
        status === "processing" ? 1 : 0;
      return priority(left.processing_status) - priority(right.processing_status)
        || Date.parse(right.uploaded_at) - Date.parse(left.uploaded_at);
    });
  const upcomingTasks = tasks
    .filter((task) => task.status !== "done")
    .sort((left, right) =>
      Number(left.status === "in_progress") - Number(right.status === "in_progress")
      || Date.parse(left.created_at) - Date.parse(right.created_at)
    )
    .slice(0, 6);

  return (
    <section className="section-content project-home" aria-labelledby="project-home-heading">
      <div className="project-home-heading">
        <div>
          <p className="eyebrow">PROJECT OVERVIEW</p>
          <h2 id="project-home-heading">Home</h2>
          <p>A quick view of what changed and what needs attention.</p>
        </div>
        <button
          className="button secondary small-button"
          type="button"
          disabled={loading}
          onClick={() => setReloadKey((current) => current + 1)}
        >
          {loading ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </div>

      <div className="project-home-grid">
        <section className="project-home-card project-home-activity" aria-labelledby="recent-changes-heading">
          <div className="project-home-card-heading">
            <Activity size={17} />
            <h3 id="recent-changes-heading">Recent changes</h3>
          </div>
          {activityError ? (
            <p className="inline-error" role="alert"><AlertCircle size={14} /> {activityError}</p>
          ) : activity.length ? (
            <ul className="project-home-list">
              {activity.map((item) => (
                <li key={item.activity_id}>
                  <span className="project-home-list-marker" />
                  <div>
                    <strong>{activityLabel(item.action)}</strong>
                    <p>{item.actor_name ?? "A collaborator"} · {new Date(item.created_at).toLocaleString()}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="project-home-empty">
              {loading ? "Loading recent changes…" : "Project updates will appear here."}
            </p>
          )}
        </section>

        <section className="project-home-card" aria-labelledby="processing-issues-heading">
          <div className="project-home-card-heading">
            <AlertCircle size={17} />
            <h3 id="processing-issues-heading">Processing issues</h3>
            <span className="project-home-count">{processingDocuments.length}</span>
          </div>
          {processingDocuments.length ? (
            <ul className="project-home-list">
              {processingDocuments.slice(0, 6).map((document) => (
                <li key={document.document_id}>
                  <span className={`project-home-status-dot status-${document.processing_status}`} />
                  <div>
                    <strong>{document.filename}</strong>
                    <p>
                      {document.processing_error
                        ?? (document.processing_status === "processing"
                          ? "Processing is still in progress."
                          : document.processing_status.replaceAll("_", " "))}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="project-home-empty">All project documents are ready.</p>
          )}
        </section>

        <section className="project-home-card" aria-labelledby="upcoming-tasks-heading">
          <div className="project-home-card-heading">
            <ListTodo size={17} />
            <h3 id="upcoming-tasks-heading">Upcoming tasks</h3>
            <span className="project-home-count">{tasks.filter((task) => task.status !== "done").length}</span>
          </div>
          {tasksError ? (
            <p className="inline-error" role="alert"><AlertCircle size={14} /> {tasksError}</p>
          ) : upcomingTasks.length ? (
            <ul className="project-home-list project-home-task-list">
              {upcomingTasks.map((task) => (
                <li key={task.task_id}>
                  <span className={`project-home-task-dot task-${task.status}`} />
                  <div>
                    <strong>{task.title}</strong>
                    <p>{taskStatusLabel(task.status)} · {task.assignee_name ?? "Unassigned"}</p>
                    <button
                      className="project-home-source-link"
                      type="button"
                      onClick={() => onOpenSource(task.source_type, task.source_id, task.source_title)}
                    >
                      {task.source_type === "document" ? "Document" : "Paper"}: {task.source_title}
                      <ArrowUpRight size={12} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="project-home-empty">
              {loading ? "Loading tasks…" : tasksError ? "" : "No open tasks right now."}
            </p>
          )}
        </section>

        <section className="project-home-card" aria-labelledby="recent-sources-heading">
          <div className="project-home-card-heading">
            <Clock3 size={17} />
            <h3 id="recent-sources-heading">Recently opened sources</h3>
          </div>
          {recentSourcesError ? (
            <p className="inline-error" role="alert"><AlertCircle size={14} /> {recentSourcesError}</p>
          ) : recentSources.length ? (
            <ul className="project-home-list">
              {recentSources.map((source) => (
                <li key={`${source.source_type}:${source.source_id}`}>
                  {source.source_type === "document" ? <FileText size={15} /> : <Library size={15} />}
                  <div>
                    <button
                      className="project-home-source-link"
                      type="button"
                      onClick={() => onOpenSource(
                        source.source_type,
                        source.source_id,
                        source.source_title,
                      )}
                    >
                      {source.source_title}
                      <ArrowUpRight size={12} />
                    </button>
                    <p>{source.source_type === "document" ? "Document" : "Paper"} · {new Date(source.opened_at).toLocaleString()}</p>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="project-home-empty">Open a document or paper to see it here.</p>
          )}
        </section>
      </div>
    </section>
  );
}
