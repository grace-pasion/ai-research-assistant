import {
  ArrowLeft,
  Download,
  FileCode2,
  FileImage,
  FileSpreadsheet,
  History,
  Info,
  LoaderCircle,
  Play,
  Plus,
  RotateCw,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import CodeMirror from "@uiw/react-codemirror";
import { downloadFile, fetchFileBlob } from "./api";
import {
  MAX_INPUT_FILE_COUNT,
  MAX_PYTHON_SOURCE_FILE_COUNT,
  type PythonSourceFile,
  type PythonOutput,
  validatePythonInputs,
  validatePythonSourceFiles,
} from "./pythonWorkspace";

type PythonArtifact = {
  filename: string;
  content_type: string;
  byte_size: number;
  updated_at: string;
  script_filename: string | null;
  input_filenames: string[];
};

type WorkspaceVersion = {
  version_id: string;
  filename: string;
  version_number: number;
  created_at: string;
  author_name: string | null;
};

type PythonWorkspaceData = {
  code: string;
  files?: PythonSourceFile[];
  updated_at: string | null;
  artifacts: PythonArtifact[];
};

type WorkspaceRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

type Props = {
  projectId: string;
  canEdit: boolean;
  request: WorkspaceRequest;
  selectedFilename: string;
  onExit: () => void;
  onFilesChange: (filenames: string[]) => void;
  onSelectedFileChange: (filename: string) => void;
  onInsertOutput: (filename: string) => void;
};

type Preview =
  | { filename: string; kind: "image"; url: string }
  | { filename: string; kind: "text"; text: string };

type WorkerReply = {
  requestId: number;
  stdout: string;
  error: string | null;
  warnings: string[];
  outputs: PythonOutput[];
};

const RUN_TIMEOUT_MS = 180_000;
const MAX_CODE_LENGTH = 100_000;
const PYTHON_EXTENSIONS = [python()];

export function PythonAnalysisWorkspace({
  projectId,
  canEdit,
  request,
  selectedFilename,
  onExit,
  onFilesChange,
  onSelectedFileChange,
  onInsertOutput,
}: Props) {
  const [workspace, setWorkspace] = useState<PythonWorkspaceData>({
    code: "",
    files: [],
    updated_at: null,
    artifacts: [],
  });
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<"saved" | "unsaved" | "error">("saved");
  const [error, setError] = useState("");
  const [inputError, setInputError] = useState("");
  const [runOutput, setRunOutput] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [inputFiles, setInputFiles] = useState<File[]>([]);
  const [creatingFile, setCreatingFile] = useState(false);
  const [newFilename, setNewFilename] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyVersions, setHistoryVersions] = useState<WorkspaceVersion[]>([]);
  const [historyFilename, setHistoryFilename] = useState(selectedFilename);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [restoringVersion, setRestoringVersion] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const savedFilesRef = useRef("");
  const updatedAtRef = useRef<string | null>(null);
  const workspaceRef = useRef(workspace);
  const selectedFilenameRef = useRef(selectedFilename);
  const workerRef = useRef<Worker | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const requestIdRef = useRef(0);
  const previewUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const path = `/api/projects/${projectId}/python`;
  selectedFilenameRef.current = selectedFilename;

  function normalizeWorkspace(data: PythonWorkspaceData): PythonWorkspaceData {
    const files = data.files?.length
      ? data.files
      : [{ filename: "main.py", code: data.code }];
    const mainCode = files.find((file) => file.filename.toLowerCase() === "main.py")?.code ?? data.code;
    return { ...data, code: mainCode, files };
  }

  function replaceWorkspace(data: PythonWorkspaceData) {
    workspaceRef.current = data;
    setWorkspace(data);
  }

  function publishFiles(files: PythonSourceFile[]) {
    onFilesChange(files.map((file) => file.filename));
  }

  function acceptWorkspace(data: PythonWorkspaceData) {
    const normalized = normalizeWorkspace(data);
    replaceWorkspace(normalized);
    savedFilesRef.current = JSON.stringify(normalized.files);
    updatedAtRef.current = normalized.updated_at;
    publishFiles(normalized.files ?? []);
    if (!normalized.files?.some((file) => file.filename === selectedFilenameRef.current)) {
      onSelectedFileChange("main.py");
    }
  }

  useEffect(() => {
    let active = true;
    mountedRef.current = true;
    setLoading(true);
    setLoaded(false);
    setError("");
    request<PythonWorkspaceData>(path)
      .then((data) => {
        if (!active) return;
        acceptWorkspace(data);
        setStatus("saved");
        setLoaded(true);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Could not load the Python workspace.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      mountedRef.current = false;
      workerRef.current?.terminate();
      workerRef.current = null;
      if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, [path, request, onFilesChange, onSelectedFileChange]);

  async function reloadWorkspace() {
    setLoading(true);
    setError("");
    try {
      const data = await request<PythonWorkspaceData>(path);
      acceptWorkspace(data);
      setStatus("saved");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reload the Python workspace.");
    } finally {
      setLoading(false);
    }
  }

  async function saveCode(): Promise<boolean> {
    const current = workspaceRef.current;
    const files = current.files ?? [];
    if (!canEdit || JSON.stringify(files) === savedFilesRef.current) return true;
    if (restoringVersion !== null) return false;
    const validation = validatePythonSourceFiles(files);
    if (validation) {
      setStatus("error");
      setError(validation);
      return false;
    }
    setSaving(true);
    setError("");
    try {
      const saved = await request<PythonWorkspaceData>(path, {
        method: "PUT",
        body: JSON.stringify({
          files,
          expected_updated_at: updatedAtRef.current,
        }),
      });
      acceptWorkspace(saved);
      setStatus("saved");
      return true;
    } catch (cause) {
      setStatus("error");
      setError(cause instanceof Error ? cause.message : "Could not save Python code.");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function loadHistory(preferredFilename = selectedFilename) {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const versions = await request<WorkspaceVersion[]>(`${path}/history`);
      setHistoryVersions(versions);
      const filenames = Array.from(new Set(versions.map((version) => version.filename))).sort();
      setHistoryFilename(
        filenames.includes(preferredFilename) ? preferredFilename : filenames[0] ?? preferredFilename,
      );
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not load Python file history.");
    } finally {
      setHistoryLoading(false);
    }
  }

  async function restoreVersion(version: WorkspaceVersion) {
    if (!window.confirm(
      `Restore ${version.filename} to version ${version.version_number}? This replaces the shared file and discards any unsaved edits.`,
    )) return;
    setRestoringVersion(version.version_id);
    setHistoryError("");
    try {
      const restored = await request<PythonWorkspaceData>(
        `${path}/history/${version.version_id}/restore`,
        {
          method: "POST",
          body: JSON.stringify({ expected_updated_at: updatedAtRef.current }),
        },
      );
      acceptWorkspace(restored);
      onSelectedFileChange(version.filename);
      setStatus("saved");
      await loadHistory(version.filename);
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not restore this Python version.");
    } finally {
      setRestoringVersion(null);
    }
  }

  function updateCode(filename: string, code: string) {
    if (restoringVersion !== null) return;
    const files = (workspaceRef.current.files ?? []).map((file) => (
      file.filename === filename ? { ...file, code } : file
    ));
    const mainCode = files.find((file) => file.filename.toLowerCase() === "main.py")?.code ?? "";
    const updated = { ...workspaceRef.current, code: mainCode, files };
    replaceWorkspace(updated);
    setStatus(JSON.stringify(files) === savedFilesRef.current ? "saved" : "unsaved");
  }

  function updateSourceFiles(files: PythonSourceFile[]) {
    if (restoringVersion !== null) return false;
    const validation = validatePythonSourceFiles(files);
    if (validation) {
      setError(validation);
      return false;
    }
    const mainCode = files.find((file) => file.filename.toLowerCase() === "main.py")?.code ?? "";
    const updated = { ...workspaceRef.current, code: mainCode, files };
    replaceWorkspace(updated);
    publishFiles(files);
    setStatus(JSON.stringify(files) === savedFilesRef.current ? "saved" : "unsaved");
    return true;
  }

  function createSourceFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (restoringVersion !== null) return;
    const entered = newFilename.trim();
    const filename = entered.toLowerCase().endsWith(".py") ? entered : `${entered}.py`;
    const files = [...(workspaceRef.current.files ?? []), { filename, code: "" }];
    if (!updateSourceFiles(files)) return;
    setCreatingFile(false);
    setNewFilename("");
    onSelectedFileChange(filename);
    void saveCode();
  }

  function deleteSelectedFile() {
    if (restoringVersion !== null) return;
    if (selectedFilename.toLowerCase() === "main.py") return;
    const files = (workspaceRef.current.files ?? []).filter((file) => file.filename !== selectedFilename);
    if (!updateSourceFiles(files)) return;
    onSelectedFileChange("main.py");
    void saveCode();
  }

  function downloadSourceFile() {
    const code = workspaceRef.current.files?.find((file) => file.filename === selectedFilename)?.code;
    if (code === undefined) return;
    const url = URL.createObjectURL(new Blob([code], { type: "text/x-python;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = selectedFilename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function changeInputFiles(files: File[]) {
    if (restoringVersion !== null) return;
    const validation = validatePythonInputs(files);
    setInputError(validation ?? "");
    setInputFiles(validation ? [] : files);
  }

  async function runCode() {
    if (!canEdit || running || loading || !loaded || restoringVersion !== null) return;
    setError("");
    setInputError("");
    setPreviewError("");
    const validation = validatePythonInputs(inputFiles);
    if (validation) {
      setInputError(validation);
      return;
    }
    if (!(await saveCode())) return;
    setRunning(true);
    setRunOutput("Loading Python and running your analysis…");
    const filesToRun = workspaceRef.current.files ?? [];
    try {
      const inputs = await Promise.all(inputFiles.map(async (file) => ({
        name: file.name,
        content: await file.arrayBuffer(),
      })));
      if (!mountedRef.current) return;
      const worker = workerRef.current ?? new Worker(
        new URL("./pythonRunner.worker.ts", import.meta.url),
        { type: "module" },
      );
      workerRef.current = worker;
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;

      worker.onmessage = (event: MessageEvent<WorkerReply>) => {
        if (event.data.requestId !== requestId) return;
        if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
        void handleWorkerReply(event.data);
      };
      worker.onerror = (event) => {
        if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
        worker.terminate();
        workerRef.current = null;
        setRunning(false);
        setError(event.message || "The Python worker failed.");
        setRunOutput("");
      };
      timeoutRef.current = window.setTimeout(() => {
        worker.terminate();
        workerRef.current = null;
        timeoutRef.current = null;
        if (!mountedRef.current) return;
        setRunning(false);
        setError("Python exceeded the 3-minute run limit. The worker was stopped.");
        setRunOutput("");
      }, RUN_TIMEOUT_MS);
      worker.postMessage(
        { requestId, entrypoint: selectedFilename, files: filesToRun, inputs },
        inputs.map((input) => input.content),
      );
    } catch (cause) {
      setRunning(false);
      setError(cause instanceof Error ? cause.message : "Could not start the Python worker.");
      setRunOutput("");
    }
  }

  async function handleWorkerReply(reply: WorkerReply) {
    if (!mountedRef.current) return;
    setRunOutput(reply.stdout || "");
    if (reply.error) {
      setRunning(false);
      setError(reply.error);
      return;
    }
    try {
      if (reply.outputs.length) {
        const form = new FormData();
        form.append("script_filename", selectedFilename);
        form.append("input_filenames", JSON.stringify(inputFiles.map((file) => file.name)));
        for (const output of reply.outputs) {
          form.append("files", new Blob([output.content]), output.name);
        }
        const artifacts = await request<PythonArtifact[]>(`${path}/artifacts`, {
          method: "PUT",
          body: form,
        });
        setWorkspace((current) => ({ ...current, artifacts }));
      }
      const messages = [
        reply.stdout.trim(),
        ...reply.warnings,
        ...(reply.outputs.length ? [] : ["No supported outputs found. Save PNG, CSV, TSV, or TeX files in /outputs."]),
      ].filter(Boolean);
      setRunOutput(messages.join("\n") || "Run complete.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save generated outputs.");
    } finally {
      if (mountedRef.current) setRunning(false);
    }
  }

  async function downloadArtifact(filename: string) {
    setError("");
    try {
      await downloadFile(
        `${path}/artifacts/${encodeURIComponent(filename)}`,
        filename,
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not download this output.");
    }
  }

  async function previewArtifact(artifact: PythonArtifact) {
    setPreviewError("");
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setPreview(null);
    try {
      const blob = await fetchFileBlob(`${path}/artifacts/${encodeURIComponent(artifact.filename)}`);
      if (artifact.content_type === "image/png") {
        const url = URL.createObjectURL(blob);
        previewUrlRef.current = url;
        setPreview({ filename: artifact.filename, kind: "image", url });
      } else {
        setPreview({
          filename: artifact.filename,
          kind: "text",
          text: (await blob.text()).split(/\r?\n/).slice(0, 100).join("\n"),
        });
      }
    } catch (cause) {
      setPreviewError(cause instanceof Error ? cause.message : "Could not preview this output.");
    }
  }

  async function deleteArtifact(filename: string) {
    setError("");
    try {
      await request<void>(`${path}/artifacts/${encodeURIComponent(filename)}`, {
        method: "DELETE",
      });
      setWorkspace((current) => ({
        ...current,
        artifacts: current.artifacts.filter((artifact) => artifact.filename !== filename),
      }));
      if (preview?.filename === filename) {
        if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = null;
        setPreview(null);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this output.");
    }
  }

  const selectedSource = workspace.files?.find((file) => file.filename === selectedFilename);

  return (
    <section className="python-workspace" aria-label="Python figures and tables workspace">
      <header className="python-workspace-header">
        <div>
          <div className="python-workspace-title">
            <FileCode2 size={14} />
            <h3>Python analysis</h3>
          </div>
          <p>Run Python in your browser and include generated outputs in the LaTeX draft.</p>
        </div>
        <div className="python-workspace-header-actions">
          <span className={`python-save-status ${status}`} role="status">
            {status === "unsaved" ? "Unsaved files" : status === "error" ? "Save failed" : "Files saved"}
          </span>
          <button
            type="button"
            className="button secondary small-button"
            onClick={() => {
              const nextOpen = !historyOpen;
              setHistoryOpen(nextOpen);
              if (nextOpen) void loadHistory(selectedFilename);
            }}
            disabled={!loaded || loading}
            aria-expanded={historyOpen}
          >
            <History size={13} /> History
          </button>
          <button type="button" className="button secondary small-button" onClick={onExit}>
            <ArrowLeft size={13} /> Back to LaTeX
          </button>
        </div>
      </header>
      {error && <p className="inline-error latex-error" role="alert">{error}</p>}
      {historyOpen && (
        <section className="workspace-history python-workspace-history" aria-label="Python version history">
          <div className="workspace-history-heading">
            <strong>Python file history</strong>
            <button
              type="button"
              className="button secondary small-button"
              onClick={() => void loadHistory(historyFilename)}
              disabled={historyLoading}
            >
              {historyLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <p>Up to 20 changed versions are kept per file. Restoring a version creates a new revision.</p>
          {historyError && <p className="inline-error" role="alert">{historyError}</p>}
          {historyVersions.length > 0 && (
            <label className="python-history-file">
              File
              <select
                value={historyFilename}
                onChange={(event) => setHistoryFilename(event.target.value)}
              >
                {Array.from(new Set(historyVersions.map((version) => version.filename))).sort()
                  .map((filename) => <option value={filename} key={filename}>{filename}</option>)}
              </select>
            </label>
          )}
          {historyLoading ? (
            <p className="latex-empty">Loading history…</p>
          ) : historyVersions.length ? historyVersions
            .filter((version) => version.filename === historyFilename)
            .map((version) => (
              <div className="workspace-history-item" key={version.version_id}>
                <span>
                  <strong>Version {version.version_number}</strong>
                  <small>{new Date(version.created_at).toLocaleString()} · {version.author_name ?? "Earlier version"}</small>
                </span>
                <button
                  type="button"
                  className="button secondary small-button"
                  onClick={() => void restoreVersion(version)}
                  disabled={!canEdit || saving || running || restoringVersion !== null}
                >
                  {restoringVersion === version.version_id ? "Restoring…" : "Restore"}
                </button>
              </div>
            )) : <p className="latex-empty">No saved Python versions yet.</p>}
        </section>
      )}
      {error.includes("changed in another session") && (
        <button type="button" className="button secondary small-button" onClick={() => void reloadWorkspace()}>
          <RotateCw size={13} /> Reload latest files
        </button>
      )}
      {!loading && (
        <div className="python-file-switcher">
          <span className="python-file-switcher-label">Python files <small>Select a file to switch scripts</small></span>
          <div className="python-file-tabs" role="group" aria-label="Python files">
            {workspace.files?.map((file) => (
              <button
                type="button"
                className="python-file-tab"
                aria-pressed={selectedFilename === file.filename}
                key={file.filename}
                onClick={() => onSelectedFileChange(file.filename)}
              >
                <FileCode2 size={13} /> {file.filename}
              </button>
            ))}
          </div>
        </div>
      )}
      {!canEdit && (
        <p className="python-read-only-notice">
          <Info size={15} />
          <span><strong>Read-only access.</strong> Ask the project owner for Editor access to add or change Python files.</span>
        </p>
      )}
      {!loading && (
        <div className="python-source-toolbar">
          <span><FileCode2 size={14} /> {selectedFilename}</span>
          <div>
            <button type="button" className="button secondary small-button" onClick={downloadSourceFile}>
              <Download size={13} /> Download file
            </button>
            {canEdit && (
              <>
                <button
                  type="button"
                  className="button secondary small-button"
                  onClick={() => {
                    setNewFilename("");
                    setCreatingFile((current) => !current);
                  }}
                  disabled={
                    !loaded
                    || saving
                    || running
                    || restoringVersion !== null
                    || (workspace.files?.length ?? 0) >= MAX_PYTHON_SOURCE_FILE_COUNT
                  }
                >
                  <Plus size={13} /> New file
                </button>
                <button
                  type="button"
                  className="button secondary small-button python-delete-source"
                  onClick={deleteSelectedFile}
                  disabled={!loaded || saving || running || restoringVersion !== null || selectedFilename.toLowerCase() === "main.py"}
                  aria-label={`Delete ${selectedFilename}`}
                  title={selectedFilename.toLowerCase() === "main.py" ? "main.py is required" : "Delete this file"}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </>
            )}
          </div>
        </div>
      )}
      {creatingFile && canEdit && (
        <form className="python-new-file-form" onSubmit={createSourceFile}>
          <label htmlFor="python-new-filename">New Python filename</label>
          <input
            id="python-new-filename"
            autoFocus
            value={newFilename}
            onChange={(event) => setNewFilename(event.currentTarget.value)}
            placeholder="analysis.py"
            maxLength={128}
            disabled={!loaded || saving || running || restoringVersion !== null}
          />
          <button type="submit" className="button primary small-button" disabled={!loaded || saving || running || restoringVersion !== null}>
            Create file
          </button>
          <button type="button" className="button secondary small-button" onClick={() => setCreatingFile(false)}>
            Cancel
          </button>
        </form>
      )}
      {loading ? (
        <div className="latex-loading"><LoaderCircle className="spin" size={18} /> Loading Python workspace…</div>
      ) : (
        <>
          <CodeMirror
            className="python-code-editor"
            aria-label="Python analysis code"
            height="400px"
            theme={oneDark}
            extensions={PYTHON_EXTENSIONS}
            indentWithTab
            editable={canEdit && loaded && !saving && !running && restoringVersion === null}
            readOnly={!canEdit || !loaded || saving || running || restoringVersion !== null}
            value={selectedSource?.code ?? ""}
            onChange={(code) => {
              if (code.length <= MAX_CODE_LENGTH) updateCode(selectedFilename, code);
            }}
          />
          <div className="python-workspace-controls">
            <label className="python-input-label">
              <Upload size={13} /> Add CSV/TSV inputs
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.tsv,text/csv,text/tab-separated-values"
                multiple
                disabled={!canEdit || saving || running || restoringVersion !== null}
                onChange={(event) => changeInputFiles(Array.from(event.currentTarget.files ?? []))}
              />
            </label>
            <span className="python-input-hint">
              Up to {MAX_INPUT_FILE_COUNT} files · 5 MB each · available only for this run
            </span>
            {canEdit && (
              <>
                <button
                  type="button"
                  className="button secondary small-button"
                  onClick={() => void saveCode()}
                  disabled={!loaded || saving || running || restoringVersion !== null || status !== "unsaved"}
                >
                  {saving ? <LoaderCircle size={13} className="spin" /> : <Save size={13} />}
                  {saving ? "Saving…" : "Save files"}
                </button>
                <button
                  type="button"
                  className="button primary small-button"
                  onClick={() => void runCode()}
                  disabled={!loaded || saving || running || restoringVersion !== null}
                >
                  {running ? <LoaderCircle size={13} className="spin" /> : <Play size={13} />}
                  {running ? "Running…" : "Run Python"}
                </button>
              </>
            )}
          </div>
          {inputFiles.length > 0 && (
            <div className="python-input-list" aria-label="Selected data files">
              {inputFiles.map((file) => <span key={file.name}>{file.name}</span>)}
              <button
                type="button"
                className="python-clear-inputs"
                onClick={() => {
                  setInputFiles([]);
                  setInputError("");
                  if (fileInputRef.current) fileInputRef.current.value = "";
                }}
                disabled={running}
              >
                Clear inputs
              </button>
            </div>
          )}
          {inputError && <p className="inline-error latex-error" role="alert">{inputError}</p>}
          <p className="python-workspace-note">
            Input files stay in this browser. In Python, read them from <code>/inputs</code> and save supported
            outputs to <code>/outputs</code>. The first run downloads the Python runtime and data-science packages.
          </p>
          {runOutput && <pre className="python-run-output" aria-label="Python output">{runOutput}</pre>}
          <div className="python-artifacts">
            <div className="python-artifacts-heading">
              <FileSpreadsheet size={14} />
              <strong>Generated outputs</strong>
              <span>{workspace.artifacts.length}</span>
            </div>
            {workspace.artifacts.length ? workspace.artifacts.map((artifact) => {
              const insertionAvailable = /\.(png|tex)$/i.test(artifact.filename);
              return (
                <article className="python-artifact" key={artifact.filename}>
                  {artifact.content_type === "image/png" ? <FileImage size={14} /> : <FileSpreadsheet size={14} />}
                  <span className="python-artifact-name">{artifact.filename}</span>
                  <small>{(artifact.byte_size / 1024).toFixed(1)} KB</small>
                  <small className="python-artifact-provenance">
                    Script: {artifact.script_filename ?? "Unknown"} · Selected inputs: {artifact.input_filenames.length
                      ? artifact.input_filenames.join(", ")
                      : "None"}
                  </small>
                  <button type="button" onClick={() => void previewArtifact(artifact)}>Preview</button>
                  <button
                    type="button"
                    onClick={() => void downloadArtifact(artifact.filename)}
                  >
                    <Download size={12} /> Download
                  </button>
                  {insertionAvailable && (
                    <button
                      type="button"
                      onClick={() => onInsertOutput(artifact.filename)}
                      disabled={!canEdit}
                    >
                      Insert in LaTeX
                    </button>
                  )}
                  {canEdit && (
                    <button
                      type="button"
                      className="python-delete-output"
                      onClick={() => void deleteArtifact(artifact.filename)}
                      aria-label={`Delete ${artifact.filename}`}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </article>
              );
            }) : <p className="latex-empty">Run Python to create PNG figures, CSV/TSV data, or TeX tables.</p>}
            {previewError && <p className="inline-error latex-error" role="alert">{previewError}</p>}
            {preview?.kind === "image" && (
              <figure className="python-output-preview">
                <img src={preview.url} alt={`Generated output ${preview.filename}`} />
                <figcaption>{preview.filename}</figcaption>
              </figure>
            )}
            {preview?.kind === "text" && (
              <pre className="python-output-preview python-text-preview">{preview.text}</pre>
            )}
          </div>
        </>
      )}
    </section>
  );
}
