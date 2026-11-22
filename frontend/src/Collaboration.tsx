import { ArrowLeft, Check, MessageCircle, Send, UserPlus, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import type {
  Colleague,
  DirectMessage,
  MessageThread,
  Notification,
  Project,
  ProjectInvitation,
} from "./types";

type Request = <T>(path: string, options?: RequestInit) => Promise<T>;

export function ShareDialog({
  project,
  request,
  onClose,
}: {
  project: Project;
  request: Request;
  onClose: () => void;
}) {
  const [invitations, setInvitations] = useState<ProjectInvitation[]>([]);
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setInvitations(await request<ProjectInvitation[]>(
      `/api/projects/${project.project_id}/invitations`,
    ));
  }, [project.project_id, request]);

  useEffect(() => {
    refresh().catch((cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "Could not load project access."),
    );
  }, [refresh]);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await request<ProjectInvitation>(`/api/projects/${project.project_id}/invitations`, {
        method: "POST",
        body: JSON.stringify({ identifier }),
      });
      setIdentifier("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send the invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(invitation: ProjectInvitation) {
    setBusy(true);
    setError("");
    try {
      await request<void>(
        `/api/projects/${project.project_id}/invitations/${invitation.invitation_id}`,
        { method: "DELETE" },
      );
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove project access.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card collaboration-modal" role="dialog" aria-modal="true" aria-labelledby="share-title">
        <div className="modal-heading">
          <div>
            <p className="eyebrow">PROJECT ACCESS</p>
            <h2 id="share-title">Share {project.project_name}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p className="collaboration-help">Invite a registered colleague by username or email. They can accept or decline in their inbox.</p>
        <form className="collaboration-invite-form" onSubmit={(event) => void invite(event)}>
          <input
            aria-label="Username or email address"
            autoComplete="off"
            maxLength={320}
            onChange={(event) => setIdentifier(event.target.value)}
            placeholder="Username or email address"
            required
            value={identifier}
          />
          <button className="button primary" disabled={busy || !identifier.trim()}><UserPlus size={15} /> Invite</button>
        </form>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="collaboration-list">
          <div className="collaboration-list-heading">People with access</div>
          {!invitations.length && <p className="muted compact">No collaborators yet.</p>}
          {invitations.map((invitation) => (
            <div className="collaboration-person" key={invitation.invitation_id}>
              <span className="avatar">{invitation.invitee_name.slice(0, 1).toUpperCase()}</span>
              <span className="collaboration-person-info">
                <strong>{invitation.invitee_name} <small>@{invitation.invitee_username}</small></strong>
                <span>{invitation.invitee_email}</span>
              </span>
              <span className={`collaboration-status status-${invitation.status}`}>{invitation.status}</span>
              <button
                className="text-button danger-text"
                disabled={busy}
                onClick={() => void revoke(invitation)}
                type="button"
              >
                {invitation.status === "accepted" ? "Remove" : "Cancel"}
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export function InboxDialog({
  request,
  onClose,
  onProjectsUpdated,
  onUnreadCount,
}: {
  request: Request;
  onClose: () => void;
  onProjectsUpdated: () => Promise<void>;
  onUnreadCount: () => Promise<void>;
}) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [threads, setThreads] = useState<MessageThread[]>([]);
  const [selected, setSelected] = useState<Colleague | null>(null);
  const [messages, setMessages] = useState<DirectMessage[]>([]);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Colleague[]>([]);
  const [content, setContent] = useState("");
  const [activeTab, setActiveTab] = useState<"notifications" | "messages">("notifications");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [loadedNotifications, loadedThreads] = await Promise.all([
      request<Notification[]>("/api/inbox"),
      request<MessageThread[]>("/api/messages/threads"),
    ]);
    setNotifications(loadedNotifications);
    setThreads(loadedThreads);
  }, [request]);

  const refreshThread = useCallback(async (colleague: Colleague) => {
    setMessages(await request<DirectMessage[]>(`/api/messages/${colleague.user_id}`));
  }, [request]);

  useEffect(() => {
    let active = true;
    const load = () => refresh().catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load your inbox.");
    });
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setMessages([]);
      return;
    }
    let active = true;
    const load = () => refreshThread(selected).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load the conversation.");
    });
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshThread, selected]);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) {
      setMatches([]);
      return;
    }
    setMatches([]);
    let active = true;
    const timer = window.setTimeout(() => {
      request<Colleague[]>(`/api/users/search?q=${encodeURIComponent(term)}`)
        .then((loaded) => { if (active) setMatches(loaded); })
        .catch((cause: unknown) => {
          if (active) setError(cause instanceof Error ? cause.message : "Could not search colleagues.");
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query, request]);

  async function markRead(notification: Notification) {
    if (notification.read_at) return;
    await request<void>(`/api/inbox/${notification.notification_id}/read`, { method: "PATCH" });
    await onUnreadCount();
  }

  async function respond(notification: Notification, response: "accepted" | "declined") {
    if (!notification.invitation_id) return;
    setBusy(true);
    setError("");
    try {
      await request<ProjectInvitation>(`/api/invitations/${notification.invitation_id}/respond`, {
        method: "POST",
        body: JSON.stringify({ response }),
      });
      await refresh();
      await onProjectsUpdated();
      await onUnreadCount();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not respond to the invitation.");
    } finally {
      setBusy(false);
    }
  }

  function openMessage(notification: Notification) {
    void markRead(notification).catch((cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "Could not mark the notification as read."),
    );
    setSelected({
      user_id: notification.actor_id,
      username: notification.actor_username ?? "",
      name: notification.actor_name,
      email: notification.actor_email,
    });
    setActiveTab("messages");
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !content.trim()) return;
    setBusy(true);
    setError("");
    const text = content.trim();
    try {
      const sent = await request<DirectMessage>(`/api/messages/${selected.user_id}`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
      setMessages((current) => [...current, sent]);
      setContent("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send the message.");
    } finally {
      setBusy(false);
    }
  }

  function chooseColleague(colleague: Colleague) {
    setSelected(colleague);
    setQuery("");
    setMatches([]);
    setActiveTab("messages");
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card inbox-modal" role="dialog" aria-modal="true" aria-labelledby="inbox-title">
        <div className="modal-heading">
          <div>
            <p className="eyebrow">COLLABORATION</p>
            <h2 id="inbox-title">Inbox</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="inbox-tabs" role="tablist">
          <button className={activeTab === "notifications" ? "active" : ""} onClick={() => setActiveTab("notifications")} role="tab">
            Notifications
          </button>
          <button className={activeTab === "messages" ? "active" : ""} onClick={() => setActiveTab("messages")} role="tab">
            Messages
          </button>
        </div>
        {error && <p className="inline-error" role="alert">{error}</p>}
        {activeTab === "notifications" ? (
          <div className="inbox-notifications">
            {!notifications.length && <p className="muted compact">You’re all caught up.</p>}
            {notifications.map((notification) => (
              <article className={`inbox-notification ${notification.read_at ? "" : "unread"}`} key={notification.notification_id}>
                <div className="notification-icon"><MessageCircle size={16} /></div>
                <div className="notification-copy">
                  {notification.kind === "project_invitation" ? (
                    <>
                      <strong>{notification.actor_name}</strong> invited you to collaborate on <strong>{notification.project_name}</strong>.
                      <div className="notification-actions">
                        {notification.invitation_status === "pending" ? (
                          <>
                            <button className="button primary small-button" disabled={busy} onClick={() => void respond(notification, "accepted")}>
                              <Check size={13} /> Accept
                            </button>
                            <button className="button secondary small-button" disabled={busy} onClick={() => void respond(notification, "declined")}>Decline</button>
                          </>
                        ) : <span className="muted compact">Invitation {notification.invitation_status}.</span>}
                      </div>
                    </>
                  ) : notification.kind === "invitation_response" ? (
                    <>
                      <strong>{notification.actor_name}</strong> {notification.invitation_status} your invitation to <strong>{notification.project_name}</strong>.
                      <button
                        className="text-button"
                        onClick={() => void markRead(notification).then(onUnreadCount).catch((cause: unknown) =>
                          setError(cause instanceof Error ? cause.message : "Could not update the notification."),
                        )}
                      >
                        Mark read
                      </button>
                    </>
                  ) : (
                    <>
                      <strong>{notification.actor_name}</strong> sent you a message.
                      <button className="text-button" onClick={() => openMessage(notification)}>Open conversation</button>
                    </>
                  )}
                  <small>{new Date(notification.created_at).toLocaleString()}</small>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="inbox-messages">
            <aside className="inbox-threads">
              <label className="inbox-search">
                <span>Find a colleague</span>
                <input
                  autoComplete="off"
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Username, name, or email"
                  value={query}
                />
              </label>
              {matches.map((colleague) => (
                <button className="inbox-thread" key={colleague.user_id} onClick={() => chooseColleague(colleague)}>
                  <span className="avatar">{colleague.name.slice(0, 1).toUpperCase()}</span>
                  <span><strong>{colleague.name}</strong><small>@{colleague.username} · {colleague.email}</small></span>
                </button>
              ))}
              {threads.map((thread) => (
                <button
                  className={`inbox-thread ${selected?.user_id === thread.user.user_id ? "selected" : ""}`}
                  key={thread.user.user_id}
                  onClick={() => chooseColleague(thread.user)}
                >
                  <span className="avatar">{thread.user.name.slice(0, 1).toUpperCase()}</span>
                  <span><strong>{thread.user.name}</strong><small>{thread.last_message}</small></span>
                  {thread.unread_count > 0 && <b className="thread-unread">{thread.unread_count}</b>}
                </button>
              ))}
            </aside>
            <div className="inbox-conversation">
              {selected ? (
                <>
                  <header className="inbox-conversation-header">
                    <button className="icon-button" onClick={() => setSelected(null)} aria-label="Back to conversations"><ArrowLeft size={16} /></button>
                    <span><strong>{selected.name}</strong><small>@{selected.username} · {selected.email}</small></span>
                  </header>
                  <div className="inbox-message-list" aria-live="polite">
                    {messages.map((message) => (
                      <div className={`direct-message ${message.sender_id === selected.user_id ? "received" : "sent"}`} key={message.message_id}>
                        <p>{message.content}</p>
                        <small>{new Date(message.created_at).toLocaleTimeString()}</small>
                      </div>
                    ))}
                    {!messages.length && <p className="muted compact">Start a conversation with {selected.name}.</p>}
                  </div>
                  <form className="inbox-compose" onSubmit={(event) => void sendMessage(event)}>
                    <input
                      aria-label="Message"
                      maxLength={5000}
                      onChange={(event) => setContent(event.target.value)}
                      placeholder="Write a message…"
                      value={content}
                    />
                    <button className="button primary" disabled={busy || !content.trim()} aria-label="Send message"><Send size={15} /></button>
                  </form>
                </>
              ) : (
                <div className="inbox-empty">
                  <MessageCircle size={24} />
                  <p>Select a conversation or search for a colleague to message.</p>
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
