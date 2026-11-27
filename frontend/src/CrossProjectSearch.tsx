import { AlertCircle, FileText, Library, Search } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { crossProjectSearchParams } from "./searchHistory";
import type { CrossProjectSearchRecord, CrossProjectSearchResult, Project } from "./types";

const SEARCH_PAGE_SIZE = 50;
const FILTER_LABELS: Record<string, string> = {
  author: "Author",
  limit: "Page size",
  project_id: "Project",
  source_type: "Source type",
  tag: "Tag",
  year: "Year",
};

type Props = {
  projects: Project[];
  request: <T,>(path: string, options?: RequestInit) => Promise<T>;
  onOpen: (result: CrossProjectSearchResult) => void;
};

export function CrossProjectSearch({ projects, request, onOpen }: Props) {
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [author, setAuthor] = useState("");
  const [year, setYear] = useState("");
  const [tag, setTag] = useState("");
  const [results, setResults] = useState<CrossProjectSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [activeSearchParams, setActiveSearchParams] = useState("");
  const [history, setHistory] = useState<CrossProjectSearchRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    let active = true;
    request<CrossProjectSearchRecord[]>("/api/search/history?limit=10")
      .then((loaded) => {
        if (active) setHistory(loaded);
      })
      .catch((cause) => {
        if (active) {
          setHistoryError(cause instanceof Error ? cause.message : "Could not load search history.");
        }
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request]);

  function buildSearchParams() {
    const params = new URLSearchParams({
      q: query.trim(),
      limit: String(SEARCH_PAGE_SIZE),
    });
    if (projectId) params.set("project_id", projectId);
    if (sourceType) params.set("source_type", sourceType);
    if (author.trim()) params.set("author", author.trim());
    if (year) params.set("year", year);
    if (tag.trim()) params.set("tag", tag.trim());
    return params;
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2) {
      setError("Enter at least two characters to search.");
      return;
    }

    setLoading(true);
    setError("");
    setSearched(true);
    setHasMore(false);
    const params = buildSearchParams();
    setActiveSearchParams(params.toString());
    try {
      const loaded = await request<CrossProjectSearchResult[]>(`/api/search?${params.toString()}`);
      setResults(loaded);
      setHasMore(loaded.length === SEARCH_PAGE_SIZE);
      void refreshHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not search across projects.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (loading || loadingMore || !hasMore) return;
    setLoadingMore(true);
    setError("");
    const params = new URLSearchParams(activeSearchParams);
    params.set("offset", String(results.length));
    try {
      const loaded = await request<CrossProjectSearchResult[]>(`/api/search?${params.toString()}`);
      setResults((current) => [...current, ...loaded]);
      setHasMore(loaded.length === SEARCH_PAGE_SIZE);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load more search results.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function refreshHistory() {
    try {
      const loaded = await request<CrossProjectSearchRecord[]>("/api/search/history?limit=10");
      setHistory(loaded);
      setHistoryError("");
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Could not refresh search history.");
    }
  }

  async function rerunHistory(record: CrossProjectSearchRecord) {
    if (loading || loadingMore) return;
    const params = crossProjectSearchParams(record);
    setQuery(record.query_text);
    setProjectId(String(record.filters.project_id ?? ""));
    setSourceType(String(record.filters.source_type ?? ""));
    setAuthor(String(record.filters.author ?? ""));
    setYear(String(record.filters.year ?? ""));
    setTag(String(record.filters.tag ?? ""));
    setActiveSearchParams(params.toString());
    setSearched(true);
    setHasMore(false);
    setLoading(true);
    setError("");
    try {
      const loaded = await request<CrossProjectSearchResult[]>(`/api/search?${params.toString()}`);
      setResults(loaded);
      setHasMore(loaded.length === SEARCH_PAGE_SIZE);
      void refreshHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not rerun this search.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  function displayFilters(filters: CrossProjectSearchRecord["filters"]) {
    return Object.entries(filters).map(([key, value]) => {
      const displayValue = key === "project_id"
        ? projects.find((project) => project.project_id === value)?.project_name ?? value
        : value;
      return `${FILTER_LABELS[key] ?? key}: ${displayValue}`;
    }).join(" · ");
  }

  return (
    <section className="section-content cross-project-search">
      <div className="section-heading">
        <div>
          <p className="eyebrow">YOUR RESEARCH LIBRARY</p>
          <h2>Search all projects</h2>
          <p>Find saved papers and documents across projects you can access.</p>
        </div>
      </div>
      <form className="cross-project-search-form" onSubmit={(event) => void search(event)}>
        <label className="cross-project-query">
          Search terms
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title, abstract, document text, or DOI…"
            minLength={2}
            maxLength={200}
            required
          />
        </label>
        <label>
          Project
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            <option value="">All accessible projects</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.project_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source type
          <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
            <option value="">All sources</option>
            <option value="paper">Papers</option>
            <option value="document">Documents</option>
          </select>
        </label>
        <label>
          Author
          <input
            value={author}
            onChange={(event) => setAuthor(event.target.value)}
            placeholder="Any author"
            maxLength={255}
          />
        </label>
        <label>
          Year
          <input
            type="number"
            value={year}
            onChange={(event) => setYear(event.target.value)}
            placeholder="Any year"
            min={1000}
            max={2100}
          />
        </label>
        <label>
          Tag
          <input
            value={tag}
            onChange={(event) => setTag(event.target.value)}
            placeholder="Exact tag"
            maxLength={64}
          />
        </label>
        <button className="button primary cross-project-search-submit" disabled={loading || loadingMore}>
          <Search size={15} /> {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p className="inline-error cross-project-search-error" role="alert">
          <AlertCircle size={15} /> {error}
        </p>
      )}
      {loading && <p className="muted compact" role="status">Searching accessible projects…</p>}
      {loadingMore && <p className="muted compact" role="status">Loading more results…</p>}
      {!loading && searched && (!error || results.length > 0) && (
        <div className="cross-project-search-results" aria-live="polite">
          <div className="result-label">
            <span>{hasMore ? `Showing ${results.length}+ matches` : `${results.length} ${results.length === 1 ? "match" : "matches"}`}</span>
          </div>
          {results.length ? results.map((result) => (
            <article
              className="cross-project-result"
              key={`${result.project_id}.${result.source_type}.${result.source_id}`}
            >
              <div className="cross-project-result-heading">
                <span className="cross-project-result-type">
                  {result.source_type === "paper" ? <Library size={13} /> : <FileText size={13} />}
                  {result.source_type === "paper" ? "PAPER" : "DOCUMENT"}
                </span>
                <span>{result.project_name}</span>
              </div>
              <button
                type="button"
                className="cross-project-result-title"
                onClick={() => onOpen(result)}
              >
                {result.title}
              </button>
              <p className="cross-project-result-details">
                {[result.authors.join(", "), result.year].filter(Boolean).join(" · ") || "No author or year metadata"}
              </p>
              {result.excerpt && <p className="cross-project-result-excerpt">{result.excerpt}</p>}
              {!!result.tags.length && (
                <div className="cross-project-result-tags" aria-label="Source tags">
                  {result.tags.map((item) => <span key={item}>{item}</span>)}
                </div>
              )}
            </article>
          )) : <p className="muted compact">No sources matched those search terms and filters.</p>}
          {hasMore && (
            <button
              type="button"
              className="button secondary small-button"
              disabled={loadingMore}
              onClick={() => void loadMore()}
            >
              {loadingMore ? "Loading…" : "Load more results"}
            </button>
          )}
        </div>
      )}
      <section className="cross-project-search-history" aria-labelledby="cross-project-history-title">
        <div className="result-label">
          <span id="cross-project-history-title">Recent search records</span>
          <small>{history.length} saved</small>
        </div>
        {historyError && <p className="inline-error" role="alert">{historyError}</p>}
        {historyLoading ? (
          <p className="muted compact" role="status">Loading search records…</p>
        ) : history.length ? history.map((record) => (
          <article className="saved-search-row cross-project-history-row" key={record.record_id}>
            <div className="saved-search-copy">
              <strong>{record.query_text}</strong>
              <small>
                {record.provider === "project_library" ? "Project library" : record.provider} · {new Date(record.searched_at).toLocaleString()} · {record.result_count} matches
              </small>
              <small>Filters: {displayFilters(record.filters) || "None"}</small>
            </div>
            <button
              className="button secondary small-button"
              type="button"
              disabled={loading || loadingMore}
              onClick={() => void rerunHistory(record)}
            >
              Rerun
            </button>
          </article>
        )) : (
          <p className="muted compact">Search records will appear here after your first search.</p>
        )}
      </section>
    </section>
  );
}
