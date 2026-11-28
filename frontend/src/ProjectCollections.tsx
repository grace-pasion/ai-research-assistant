import { AlertCircle, FileText, Library, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { jsonBody } from "./api";
import { confirmDestructiveAction } from "./destructiveConfirmation";
import type {
  DocumentRecord,
  Paper,
  ProjectCollection,
  ProjectCollectionItem,
} from "./types";

type Props = {
  projectId: string;
  documents: DocumentRecord[];
  papers: Paper[];
  canEdit: boolean;
  request: <T,>(path: string, options?: RequestInit) => Promise<T>;
  onOpenSource: (
    sourceType: "document" | "paper",
    sourceId: string,
    sourceTitle: string,
  ) => void;
};

function messageFromError(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

export function ProjectCollections({
  projectId,
  documents,
  papers,
  canEdit,
  request,
  onOpenSource,
}: Props) {
  const [collections, setCollections] = useState<ProjectCollection[]>([]);
  const [collectionName, setCollectionName] = useState("");
  const [renaming, setRenaming] = useState<Record<string, string>>({});
  const [selectedSources, setSelectedSources] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busyCollectionId, setBusyCollectionId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setCollections([]);
    setSelectedSources({});
    setRenaming({});
    setLoading(true);
    setError("");
    request<ProjectCollection[]>(`/api/projects/${projectId}/collections`)
      .then((loaded) => {
        if (active) setCollections(loaded);
      })
      .catch((cause: unknown) => {
        if (active) setError(messageFromError(cause, "Could not load project collections."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, request]);

  async function createCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = collectionName.trim();
    if (!name) {
      setError("Enter a collection name.");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const created = await request<ProjectCollection>(
        `/api/projects/${projectId}/collections`,
        { method: "POST", body: jsonBody({ name }) },
      );
      setCollections((current) => [created, ...current]);
      setCollectionName("");
    } catch (cause) {
      setError(messageFromError(cause, "Could not create the collection."));
    } finally {
      setCreating(false);
    }
  }

  async function renameCollection(
    event: FormEvent<HTMLFormElement>,
    collection: ProjectCollection,
  ) {
    event.preventDefault();
    const name = (renaming[collection.collection_id] ?? collection.name).trim();
    if (!name) {
      setError("Enter a collection name.");
      return;
    }
    if (name === collection.name) return;
    setBusyCollectionId(collection.collection_id);
    setError("");
    try {
      const updated = await request<ProjectCollection>(
        `/api/projects/${projectId}/collections/${collection.collection_id}`,
        { method: "PATCH", body: jsonBody({ name }) },
      );
      setCollections((current) => current.map((item) =>
        item.collection_id === updated.collection_id ? updated : item
      ));
      setRenaming((current) => ({ ...current, [collection.collection_id]: updated.name }));
    } catch (cause) {
      setError(messageFromError(cause, "Could not rename the collection."));
    } finally {
      setBusyCollectionId(null);
    }
  }

  async function deleteCollection(collection: ProjectCollection) {
    if (!confirmDestructiveAction(
      "Delete",
      collection.name,
      "This removes the collection and its links; papers and documents remain in the project.",
    )) return;
    setBusyCollectionId(collection.collection_id);
    setError("");
    try {
      await request<void>(
        `/api/projects/${projectId}/collections/${collection.collection_id}`,
        { method: "DELETE" },
      );
      setCollections((current) => current.filter(
        (item) => item.collection_id !== collection.collection_id
      ));
    } catch (cause) {
      setError(messageFromError(cause, "Could not delete the collection."));
    } finally {
      setBusyCollectionId(null);
    }
  }

  async function addSource(
    event: FormEvent<HTMLFormElement>,
    collection: ProjectCollection,
  ) {
    event.preventDefault();
    const selection = selectedSources[collection.collection_id] ?? "";
    const separator = selection.indexOf(":");
    const sourceType = selection.slice(0, separator);
    const sourceId = selection.slice(separator + 1);
    if (
      separator < 0
      || (sourceType !== "document" && sourceType !== "paper")
      || !sourceId
    ) {
      setError("Choose a saved paper or project document to add.");
      return;
    }
    setBusyCollectionId(collection.collection_id);
    setError("");
    try {
      const added = await request<ProjectCollectionItem>(
        `/api/projects/${projectId}/collections/${collection.collection_id}/items`,
        {
          method: "POST",
          body: jsonBody({ source_type: sourceType, source_id: sourceId }),
        },
      );
      setCollections((current) => current.map((item) =>
        item.collection_id === collection.collection_id
          ? { ...item, items: [...item.items, added] }
          : item
      ));
      setSelectedSources((current) => ({ ...current, [collection.collection_id]: "" }));
    } catch (cause) {
      setError(messageFromError(cause, "Could not add the source to the collection."));
    } finally {
      setBusyCollectionId(null);
    }
  }

  async function removeSource(collection: ProjectCollection, item: ProjectCollectionItem) {
    const sourceName = item.source_title || `${item.source_type} source`;
    if (!confirmDestructiveAction(
      "Remove",
      sourceName,
      `This removes it from collection “${collection.name}” but keeps the source in the project.`,
    )) return;
    setBusyCollectionId(collection.collection_id);
    setError("");
    try {
      await request<void>(
        `/api/projects/${projectId}/collections/${collection.collection_id}/items/${item.item_id}`,
        { method: "DELETE" },
      );
      setCollections((current) => current.map((entry) =>
        entry.collection_id === collection.collection_id
          ? { ...entry, items: entry.items.filter((source) => source.item_id !== item.item_id) }
          : entry
      ));
    } catch (cause) {
      setError(messageFromError(cause, "Could not remove the source from the collection."));
    } finally {
      setBusyCollectionId(null);
    }
  }

  return (
    <section className="section-content project-collections" aria-labelledby="collections-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">PROJECT LIBRARY</p>
          <h2 id="collections-heading">Saved collections</h2>
          <p>Group papers and documents into shared reading lists and synthesis sets.</p>
        </div>
      </div>

      {canEdit && (
        <form className="project-collection-create" onSubmit={(event) => void createCollection(event)}>
          <label>
            New collection
            <input
              value={collectionName}
              onChange={(event) => setCollectionName(event.target.value)}
              placeholder="Background"
              maxLength={80}
              required
            />
          </label>
          <button className="button primary" disabled={creating}>
            <Plus size={15} /> {creating ? "Creating…" : "Create collection"}
          </button>
        </form>
      )}

      {error && (
        <p className="inline-error project-collection-error" role="alert">
          <AlertCircle size={15} /> {error}
        </p>
      )}
      {loading && <p className="muted compact" role="status">Loading collections…</p>}
      {!loading && collections.length === 0 && (
        <p className="muted compact">
          {canEdit
            ? "Create a collection to group papers and documents for this project."
            : "No collections have been created for this project yet."}
        </p>
      )}

      <div className="project-collection-list">
        {collections.map((collection) => {
          const busy = busyCollectionId === collection.collection_id;
          const renameValue = renaming[collection.collection_id] ?? collection.name;
          const includedDocumentIds = new Set(
            collection.items
              .filter((item) => item.source_type === "document")
              .map((item) => item.source_id),
          );
          const includedPaperIds = new Set(
            collection.items
              .filter((item) => item.source_type === "paper")
              .map((item) => item.source_id),
          );
          const availableDocuments = documents.filter(
            (document) => !includedDocumentIds.has(document.document_id),
          );
          const availablePapers = papers.filter(
            (paper) => !includedPaperIds.has(paper.paper_id),
          );
          const hasAvailableSources = availableDocuments.length > 0 || availablePapers.length > 0;
          return (
            <article className="project-collection-card" key={collection.collection_id}>
              <div className="project-collection-header">
                <div>
                  <h3>{collection.name}</h3>
                  <p>{collection.items.length} {collection.items.length === 1 ? "source" : "sources"}</p>
                </div>
                {canEdit && (
                  <button
                    className="icon-button project-collection-delete"
                    type="button"
                    aria-label={`Delete ${collection.name}`}
                    title={`Delete ${collection.name}`}
                    disabled={busy}
                    onClick={() => void deleteCollection(collection)}
                  >
                    <Trash2 size={15} />
                  </button>
                )}
              </div>

              {canEdit && (
                <form
                  className="project-collection-rename"
                  onSubmit={(event) => void renameCollection(event, collection)}
                >
                  <label>
                    Rename
                    <input
                      value={renameValue}
                      onChange={(event) => setRenaming((current) => ({
                        ...current,
                        [collection.collection_id]: event.target.value,
                      }))}
                      maxLength={80}
                      required
                    />
                  </label>
                  <button className="button secondary small-button" disabled={busy || renameValue.trim() === collection.name}>
                    Save name
                  </button>
                </form>
              )}

              {canEdit && (
                <form
                  className="project-collection-add"
                  onSubmit={(event) => void addSource(event, collection)}
                >
                  <label>
                    Add a saved source
                    <select
                      value={selectedSources[collection.collection_id] ?? ""}
                      onChange={(event) => setSelectedSources((current) => ({
                        ...current,
                        [collection.collection_id]: event.target.value,
                      }))}
                      disabled={!hasAvailableSources || busy}
                    >
                      <option value="">
                        {!hasAvailableSources
                          ? "All saved sources are already in this collection"
                          : "Choose a paper or document"}
                      </option>
                      {availableDocuments.length > 0 && (
                        <optgroup label="Documents">
                          {availableDocuments.map((document) => (
                            <option key={document.document_id} value={`document:${document.document_id}`}>
                              {document.filename}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {availablePapers.length > 0 && (
                        <optgroup label="Papers">
                          {availablePapers.map((paper) => (
                            <option key={paper.paper_id} value={`paper:${paper.paper_id}`}>
                              {paper.title}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </label>
                  <button
                    className="button secondary small-button"
                    disabled={!hasAvailableSources || busy || !(selectedSources[collection.collection_id] ?? "")}
                  >
                    Add source
                  </button>
                </form>
              )}

              {collection.items.length > 0 ? (
                <ul className="project-collection-items">
                  {collection.items.map((item) => {
                    const title = item.source_title ?? "Unavailable source";
                    const sourceIsAvailable = item.source_type === "document"
                      ? documents.some((document) => document.document_id === item.source_id)
                      : papers.some((paper) => paper.paper_id === item.source_id);
                    return (
                      <li key={item.item_id}>
                        <span className="project-collection-source-type">
                          {item.source_type === "document" ? <FileText size={14} /> : <Library size={14} />}
                          {item.source_type === "document" ? "Document" : "Paper"}
                        </span>
                        {sourceIsAvailable ? (
                          <button
                            className="project-collection-source-title"
                            type="button"
                            onClick={() => onOpenSource(item.source_type, item.source_id, title)}
                          >
                            {title}
                          </button>
                        ) : (
                          <span className="project-collection-unavailable">{title}</span>
                        )}
                        {canEdit && (
                          <button
                            className="icon-button project-collection-remove"
                            type="button"
                            aria-label={`Remove ${title} from ${collection.name}`}
                            title="Remove from collection"
                            disabled={busy}
                            onClick={() => void removeSource(collection, item)}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted compact project-collection-empty">No sources in this collection yet.</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
