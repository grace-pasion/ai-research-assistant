import { Activity, LoaderCircle, ShieldCheck, Trash2, Users } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { api, getAdminToken, jsonBody, setAdminToken } from "./api";
import type { User } from "./types";

type AdminUser = User & {
  created_at: string;
  project_count: number;
  document_count: number;
  saved_paper_count: number;
  conversation_count: number;
  last_activity_at: string | null;
};

type ActivityEvent = {
  activity_id: string;
  user_id: string;
  email: string;
  action: string;
  details: Record<string, unknown>;
  created_at: string;
};

type Page = {
  total: number;
  limit: number;
  offset: number;
};

type AdminUserPage = Page & { users: AdminUser[] };
type ActivityPage = Page & { events: ActivityEvent[] };
type AdminLoginResponse = { access_token: string; user: User };

const PAGE_SIZE = 25;

function AdminApp() {
  const [token, setToken] = useState(getAdminToken());
  const [admin, setAdmin] = useState<User | null>(null);
  const [users, setUsers] = useState<AdminUserPage | null>(null);
  const [activity, setActivity] = useState<ActivityPage | null>(null);
  const [section, setSection] = useState<"users" | "activity">("users");
  const [userOffset, setUserOffset] = useState(0);
  const [activityOffset, setActivityOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);
  const [error, setError] = useState("");

  const request = useCallback(
    <T,>(path: string, options?: RequestInit) => api<T>(path, options, token),
    [token],
  );

  const loadData = useCallback(async () => {
    const [userPage, activityPage] = await Promise.all([
      request<AdminUserPage>(`/api/admin/users?limit=${PAGE_SIZE}&offset=${userOffset}`),
      request<ActivityPage>(`/api/admin/activity?limit=${PAGE_SIZE}&offset=${activityOffset}`),
    ]);
    setUsers(userPage);
    setActivity(activityPage);
  }, [activityOffset, request, userOffset]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    setBusy(true);
    request<User>("/api/admin/me")
      .then((currentAdmin) => {
        if (!active) return;
        setAdmin(currentAdmin);
        return loadData();
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load the admin workspace.");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [loadData, request, token]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await api<AdminLoginResponse>(
        "/api/admin/auth/login",
        {
          method: "POST",
          body: jsonBody({
            email: form.get("email"),
            password: form.get("password"),
          }),
        },
        null,
      );
      setAdminToken(result.access_token);
      setToken(result.access_token);
      setAdmin(result.user);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Administrator sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  function signOut() {
    setAdminToken(null);
    setToken(null);
    setAdmin(null);
    setUsers(null);
    setActivity(null);
    setError("");
  }

  async function deleteUser(user: AdminUser) {
    if (
      user.user_id === admin?.user_id ||
      !window.confirm(
        `Permanently delete ${user.email} and all of their projects, documents, files, conversations, and saved papers? This cannot be undone.`,
      )
    ) {
      return;
    }
    setDeletingUser(user.user_id);
    setError("");
    try {
      await request<void>(`/api/admin/users/${user.user_id}`, { method: "DELETE" });
      await loadData();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this account.");
    } finally {
      setDeletingUser(null);
    }
  }

  if (!token) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="brand-mark"><ShieldCheck size={22} /></div>
          <p className="eyebrow">FIELDNOTES ADMINISTRATION</p>
          <h1>Administrator sign in.</h1>
          <p className="muted">
            Admin access is limited to existing accounts authorized by the backend administrator
            email allowlist.
          </p>
          {error && <div className="notice error" role="alert">{error}</div>}
          <form onSubmit={signIn} className="stack-form">
            <label>
              Email
              <input name="email" type="email" autoComplete="username" required />
            </label>
            <label>
              Password
              <input name="password" type="password" autoComplete="current-password" required />
            </label>
            <button className="button primary wide" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : null}
              Sign in to admin
            </button>
          </form>
          <a className="text-button centered" href={window.location.pathname}>
            Researcher sign in
          </a>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-page">
      <div className="admin-frame">
        <header className="admin-header">
          <div className="admin-brand">
            <span className="brand-mark"><ShieldCheck size={19} /></span>
            <div>
              <p className="eyebrow">FIELDNOTES</p>
              <h1>Admin console</h1>
            </div>
          </div>
          <div className="admin-account">
            <span>{admin?.email ?? "Administrator"}</span>
            <button className="button secondary small-button" onClick={signOut}>Sign out</button>
          </div>
        </header>

        {error && <div className="notice error admin-notice" role="alert">{error}</div>}

        <section className="admin-intro">
          <div>
            <p className="eyebrow">ACCOUNT OVERSIGHT</p>
            <h2>Manage users and review activity.</h2>
            <p>
              Activity contains operational metadata only. Document contents, search terms,
              assistant prompts, and answers are not recorded for this dashboard. Tracking begins
              when this feature is deployed; earlier actions are not backfilled.
            </p>
          </div>
          <div className="admin-total">
            <Users size={18} />
            <strong>{users?.total ?? "—"}</strong>
            <span>accounts</span>
          </div>
        </section>

        <nav className="admin-tabs" aria-label="Administrator sections">
          <button
            className={section === "users" ? "active" : ""}
            onClick={() => setSection("users")}
          >
            <Users size={15} /> Users
          </button>
          <button
            className={section === "activity" ? "active" : ""}
            onClick={() => setSection("activity")}
          >
            <Activity size={15} /> Activity
          </button>
        </nav>

        {busy && !users && <p className="admin-loading"><LoaderCircle className="spin" size={16} /> Loading admin data…</p>}

        {section === "users" && (
          <section className="admin-panel">
            <div className="admin-section-heading">
              <div><h2>User accounts</h2><p>Counts and last recorded activity; no research content is exposed.</p></div>
              <span>{users?.total ?? 0} total</span>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Account</th><th>Joined</th><th>Projects</th><th>Documents</th>
                    <th>Saved papers</th><th>Conversations</th><th>Last recorded activity</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {users?.users.map((user) => (
                    <tr key={user.user_id}>
                      <td><strong>{user.name}</strong><small>{user.email}</small></td>
                      <td>{formatTimestamp(user.created_at)}</td>
                      <td>{user.project_count}</td>
                      <td>{user.document_count}</td>
                      <td>{user.saved_paper_count}</td>
                      <td>{user.conversation_count}</td>
                      <td>{formatTimestamp(user.last_activity_at)}</td>
                      <td>
                        <button
                          className="button danger small-button"
                          disabled={user.user_id === admin?.user_id || deletingUser === user.user_id}
                          onClick={() => void deleteUser(user)}
                          title={user.user_id === admin?.user_id ? "You cannot delete your own account" : "Permanently delete this account"}
                        >
                          {deletingUser === user.user_id ? <LoaderCircle className="spin" size={13} /> : <Trash2 size={13} />}
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!users?.users.length && (
                    <tr><td className="admin-empty" colSpan={8}>No accounts found.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {users && (
              <Pagination
                offset={users.offset}
                limit={users.limit}
                total={users.total}
                onChange={setUserOffset}
              />
            )}
          </section>
        )}

        {section === "activity" && (
          <section className="admin-panel">
            <div className="admin-section-heading">
              <div><h2>Recent activity</h2><p>Action types and safe metadata only; no document names, query text, prompts, or answers.</p></div>
              <span>{activity?.total ?? 0} events</span>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table activity-table">
                <thead><tr><th>Account</th><th>Action</th><th>Details</th><th>Time</th></tr></thead>
                <tbody>
                  {activity?.events.map((item) => (
                    <tr key={item.activity_id}>
                      <td><small>{item.email}</small></td>
                      <td><span className="event-label">{item.action.replaceAll(".", " ")}</span></td>
                      <td>{formatDetails(item.details)}</td>
                      <td>{formatTimestamp(item.created_at)}</td>
                    </tr>
                  ))}
                  {!activity?.events.length && (
                    <tr><td className="admin-empty" colSpan={4}>No activity recorded yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {activity && (
              <Pagination
                offset={activity.offset}
                limit={activity.limit}
                total={activity.total}
                onChange={setActivityOffset}
              />
            )}
          </section>
        )}
      </div>
    </main>
  );
}

function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="admin-pagination">
      <span>{first}–{last} of {total}</span>
      <div>
        <button className="button secondary small-button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
        <button className="button secondary small-button" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</button>
      </div>
    </div>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function formatDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
    .join(" · ") || "—";
}

export default AdminApp;
