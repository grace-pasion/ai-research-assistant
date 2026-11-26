import { ArrowLeft, Check, Hash, MessageCircle, Send, UserPlus, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import type {
  Colleague,
  DirectMessage,
  MessageThread,
  Notification,
  Project,
  ProjectInvitation,
  TeamChannel,
  TeamChannelMessage,
  TeamWorkspace,
  TeamWorkspaceInvitation,
  TeamWorkspaceMember,
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
  const [role, setRole] = useState<ProjectInvitation["role"]>("edit");
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
        body: JSON.stringify({ identifier, role }),
      });
      setIdentifier("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send the invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(invitation: ProjectInvitation, nextRole: ProjectInvitation["role"]) {
    setBusy(true);
    setError("");
    try {
      const updated = await request<ProjectInvitation>(
        `/api/projects/${project.project_id}/invitations/${invitation.invitation_id}`,
        { method: "PATCH", body: JSON.stringify({ role: nextRole }) },
      );
      setInvitations((current) => current.map((item) =>
        item.invitation_id === updated.invitation_id ? updated : item,
      ));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update project access.");
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
        <p className="collaboration-help">
          Readers can view project content. Commenters can also add notes to sources and findings.
          Editors can change shared project content. Assistant conversations stay private to each author.
        </p>
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
          <select aria-label="Collaborator role" onChange={(event) => setRole(event.target.value as ProjectInvitation["role"])} value={role}>
            <option value="read">Reader</option>
            <option value="comment">Commenter</option>
            <option value="edit">Editor</option>
          </select>
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
              <select
                aria-label={`Role for ${invitation.invitee_name}`}
                disabled={busy}
                onChange={(event) => void changeRole(invitation, event.target.value as ProjectInvitation["role"])}
                value={invitation.role}
              >
                <option value="read">Reader</option>
                <option value="comment">Commenter</option>
                <option value="edit">Editor</option>
              </select>
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
  onOpenProject,
}: {
  request: Request;
  onClose: () => void;
  onProjectsUpdated: () => Promise<void>;
  onUnreadCount: () => Promise<void>;
  onOpenProject: (projectId: string) => void;
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

  function openProjectNotes(notification: Notification) {
    void markRead(notification)
      .then(() => {
        if (notification.project_id) onOpenProject(notification.project_id);
      })
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "Could not open project notes."),
      );
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
                      <strong>{notification.actor_name}</strong> invited you to collaborate on{" "}
                      <strong>{notification.project_name}</strong> as a{" "}
                      <strong>{({ read: "Reader", comment: "Commenter", edit: "Editor" })[notification.invitation_role ?? "edit"]}</strong>.
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
                    notification.kind === "annotation_mention" ? (
                      <>
                        <strong>{notification.actor_name}</strong> mentioned you in a note about{" "}
                        <strong>{notification.details.source_title ?? "a project source"}</strong> in{" "}
                        <strong>{notification.project_name}</strong>.
                        <button className="text-button" onClick={() => openProjectNotes(notification)}>Open project notes</button>
                      </>
                    ) : notification.kind === "task_assigned" ? (
                      <>
                        <strong>{notification.actor_name}</strong> assigned you a task:{" "}
                        <strong>{notification.details.task_title ?? "Review a project source"}</strong> in{" "}
                        <strong>{notification.project_name}</strong>.
                        <button className="text-button" onClick={() => openProjectNotes(notification)}>Open project tasks</button>
                      </>
                    ) : notification.kind === "saved_search_alert" ? (
                      <>
                        <strong>New research matches</strong>: {notification.details.new_result_count ?? 0} new
                        {" "}{notification.details.provider ?? "academic search"} result
                        {(notification.details.new_result_count ?? 0) === 1 ? "" : "s"} for{" "}
                        <strong>{notification.details.query ?? "a saved search"}</strong> in{" "}
                        <strong>{notification.project_name}</strong>.
                        <button
                          className="text-button"
                          onClick={() => void markRead(notification).catch((cause: unknown) =>
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
                    )
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

export function TeamWorkspaceDialog({
  workspaces,
  userId,
  request,
  onClose,
  onChanged,
}: {
  workspaces: TeamWorkspace[];
  userId: string;
  request: Request;
  onClose: () => void;
  onChanged: (teamWorkspaceId?: string) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState(workspaces[0]?.team_workspace_id ?? "");
  const [members, setMembers] = useState<TeamWorkspaceMember[]>([]);
  const [invitations, setInvitations] = useState<TeamWorkspaceInvitation[]>([]);
  const [received, setReceived] = useState<TeamWorkspaceInvitation[]>([]);
  const [workspaceName, setWorkspaceName] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selected = workspaces.find((item) => item.team_workspace_id === selectedId) ?? null;

  useEffect(() => {
    if (!workspaces.some((item) => item.team_workspace_id === selectedId)) {
      setSelectedId(workspaces[0]?.team_workspace_id ?? "");
    }
  }, [selectedId, workspaces]);

  const refresh = useCallback(async () => {
    const pending = await request<TeamWorkspaceInvitation[]>("/api/team-workspace-invitations");
    setReceived(pending);
    if (!selected) {
      setMembers([]);
      setInvitations([]);
      return;
    }
    const [loadedMembers, loadedInvitations] = await Promise.all([
      request<TeamWorkspaceMember[]>(`/api/team-workspaces/${selected.team_workspace_id}/members`),
      selected.owner_id === userId
        ? request<TeamWorkspaceInvitation[]>(`/api/team-workspaces/${selected.team_workspace_id}/invitations`)
        : Promise.resolve([]),
    ]);
    setMembers(loadedMembers);
    setInvitations(loadedInvitations);
  }, [request, selected, userId]);

  useEffect(() => {
    refresh().catch((cause: unknown) =>
      setError(cause instanceof Error ? cause.message : "Could not load team workspace details."),
    );
  }, [refresh]);

  async function createWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await request<TeamWorkspace>("/api/team-workspaces", {
        method: "POST",
        body: JSON.stringify({ name: workspaceName }),
      });
      setWorkspaceName("");
      await onChanged(created.team_workspace_id);
      setSelectedId(created.team_workspace_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the team workspace.");
    } finally {
      setBusy(false);
    }
  }

  async function inviteMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await request<TeamWorkspaceInvitation>(
        `/api/team-workspaces/${selected.team_workspace_id}/invitations`,
        { method: "POST", body: JSON.stringify({ identifier }) },
      );
      setIdentifier("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not invite this person.");
    } finally {
      setBusy(false);
    }
  }

  async function respond(invitation: TeamWorkspaceInvitation, response: "accepted" | "declined") {
    setBusy(true);
    setError("");
    try {
      await request<TeamWorkspaceInvitation>(
        `/api/team-workspace-invitations/${invitation.invitation_id}/respond`,
        { method: "POST", body: JSON.stringify({ response }) },
      );
      await Promise.all([onChanged(invitation.team_workspace_id), refresh()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not respond to the invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(member: TeamWorkspaceMember) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      await request<void>(
        `/api/team-workspaces/${selected.team_workspace_id}/members/${member.user_id}`,
        { method: "DELETE" },
      );
      await Promise.all([onChanged(), refresh()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove the team member.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card collaboration-modal team-workspace-modal" role="dialog" aria-modal="true" aria-labelledby="team-workspace-title">
        <div className="modal-heading">
          <div><p className="eyebrow">ORGANIZATION</p><h2 id="team-workspace-title">Team workspaces</h2></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p className="collaboration-help">Create an organization workspace, invite members, and share projects and channels with your team.</p>
        <form className="collaboration-invite-form" onSubmit={(event) => void createWorkspace(event)}>
          <input aria-label="New team workspace name" maxLength={160} onChange={(event) => setWorkspaceName(event.target.value)} placeholder="New workspace name" required value={workspaceName} />
          <button className="button primary" disabled={busy || !workspaceName.trim()}><UserPlus size={15} /> Create</button>
        </form>
        {received.length > 0 && (
          <div className="collaboration-list">
            <div className="collaboration-list-heading">Invitations for you</div>
            {received.map((invitation) => (
              <div className="team-invitation" key={invitation.invitation_id}>
                <span><strong>{invitation.workspace_name}</strong><small>Invited by {invitation.inviter_name}</small></span>
                <button className="button primary small-button" disabled={busy} onClick={() => void respond(invitation, "accepted")} type="button"><Check size={13} /> Join</button>
                <button className="button secondary small-button" disabled={busy} onClick={() => void respond(invitation, "declined")} type="button">Decline</button>
              </div>
            ))}
          </div>
        )}
        {workspaces.length > 0 && (
          <label className="team-workspace-select">
            Manage workspace
            <select onChange={(event) => setSelectedId(event.target.value)} value={selectedId}>
              {workspaces.map((workspace) => <option key={workspace.team_workspace_id} value={workspace.team_workspace_id}>{workspace.name} · {workspace.member_count} members</option>)}
            </select>
          </label>
        )}
        {selected && (
          <>
            {selected.owner_id === userId && (
              <>
                <div className="collaboration-list-heading">Invite a team member</div>
                <p className="collaboration-help">Invitations go to registered Fieldnotes accounts by username or email.</p>
                <form className="collaboration-invite-form" onSubmit={(event) => void inviteMember(event)}>
                  <input aria-label="Username or email address" autoComplete="off" maxLength={320} onChange={(event) => setIdentifier(event.target.value)} placeholder="Username or email address" required value={identifier} />
                  <button className="button primary" disabled={busy || !identifier.trim()}><UserPlus size={15} /> Invite</button>
                </form>
                {invitations.map((invitation) => (
                  <div className="team-invitation" key={invitation.invitation_id}>
                    <span><strong>{invitation.invitee_name}</strong><small>{invitation.invitee_email}</small></span>
                    <span className="collaboration-status status-pending">pending</span>
                  </div>
                ))}
              </>
            )}
            <div className="collaboration-list">
              <div className="collaboration-list-heading">Members</div>
              {members.map((member) => (
                <div className="collaboration-person" key={member.user_id}>
                  <span className="avatar">{member.name.slice(0, 1).toUpperCase()}</span>
                  <span className="collaboration-person-info">
                    <strong>{member.name} <small>{member.role}</small></strong>
                    <span>{member.email}</span>
                  </span>
                  {selected.owner_id === userId && member.user_id !== userId && (
                    <button className="text-button danger-text" disabled={busy} onClick={() => void removeMember(member)} type="button">Remove</button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
        {error && <p className="inline-error" role="alert">{error}</p>}
      </section>
    </div>
  );
}

export function TeamChannelDialog({
  workspaceId,
  workspaceName,
  project,
  canCreate,
  request,
  onClose,
}: {
  workspaceId: string;
  workspaceName: string;
  project: Project | null;
  canCreate: boolean;
  request: Request;
  onClose: () => void;
}) {
  const [channels, setChannels] = useState<TeamChannel[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [messages, setMessages] = useState<TeamChannelMessage[]>([]);
  const [channelName, setChannelName] = useState("");
  const [scope, setScope] = useState(project?.project_id ?? "");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selected = channels.find((channel) => channel.channel_id === selectedId) ?? null;

  const refreshChannels = useCallback(async () => {
    const loaded = await request<TeamChannel[]>(`/api/team-workspaces/${workspaceId}/channels`);
    setChannels(loaded);
    setSelectedId((current) => loaded.some((channel) => channel.channel_id === current)
      ? current
      : loaded[0]?.channel_id ?? "");
  }, [request, workspaceId]);

  const refreshMessages = useCallback(async (channelId: string) => {
    setMessages(await request<TeamChannelMessage[]>(`/api/team-channels/${channelId}/messages`));
  }, [request]);

  useEffect(() => {
    let active = true;
    const load = () => refreshChannels().catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load team channels.");
    });
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshChannels]);

  useEffect(() => {
    if (!selected) {
      setMessages([]);
      return;
    }
    let active = true;
    const load = () => refreshMessages(selected.channel_id).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not load channel messages.");
    });
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [refreshMessages, selected]);

  async function createChannel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await request<TeamChannel>(`/api/team-workspaces/${workspaceId}/channels`, {
        method: "POST",
        body: JSON.stringify({ name: channelName, project_id: scope || null }),
      });
      setChannelName("");
      await refreshChannels();
      setSelectedId(created.channel_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the channel.");
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !content.trim()) return;
    setBusy(true);
    setError("");
    try {
      const sent = await request<TeamChannelMessage>(`/api/team-channels/${selected.channel_id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      setMessages((current) => [...current, sent]);
      setContent("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not send the channel message.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="modal-card inbox-modal team-channel-modal" role="dialog" aria-modal="true" aria-labelledby="team-channel-title">
        <div className="modal-heading">
          <div><p className="eyebrow">TEAM MESSAGES · {workspaceName}</p><h2 id="team-channel-title">Channels</h2></div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="team-channel-layout">
          <aside className="team-channel-list">
            {channels.map((channel) => (
              <button className={`team-channel-option ${channel.channel_id === selectedId ? "selected" : ""}`} key={channel.channel_id} onClick={() => setSelectedId(channel.channel_id)} type="button">
                <Hash size={14} /><span><strong>{channel.name}</strong><small>{channel.project_name ?? "Workspace-wide"}</small></span>
              </button>
            ))}
            {!channels.length && <p className="muted compact">No channels are available yet.</p>}
            {canCreate && (
              <form className="team-channel-create" onSubmit={(event) => void createChannel(event)}>
                <label>New channel<input aria-label="New channel name" maxLength={80} onChange={(event) => setChannelName(event.target.value)} placeholder="Channel name" required value={channelName} /></label>
                <label>Channel access
                  <select onChange={(event) => setScope(event.target.value)} value={scope}>
                    <option value="">Entire workspace</option>
                    {project && <option value={project.project_id}>Only {project.project_name}</option>}
                  </select>
                </label>
                <button className="button primary" disabled={busy || !channelName.trim()}><Hash size={14} /> Create channel</button>
              </form>
            )}
          </aside>
          <div className="team-channel-conversation">
            {selected ? (
              <>
                <header className="inbox-conversation-header"><Hash size={15} /><span><strong>{selected.name}</strong><small>{selected.project_name ?? "Visible to team workspace members"}</small></span></header>
                <div className="inbox-message-list" aria-live="polite">
                  {messages.map((message) => (
                    <div className="team-channel-message" key={message.message_id}>
                      <strong>{message.sender_name}</strong><p>{message.content}</p>
                      <small>{new Date(message.created_at).toLocaleString()}</small>
                    </div>
                  ))}
                  {!messages.length && <p className="muted compact">No messages yet. Start the conversation.</p>}
                </div>
                <form className="inbox-compose" onSubmit={(event) => void sendMessage(event)}>
                  <input aria-label="Channel message" maxLength={5000} onChange={(event) => setContent(event.target.value)} placeholder={`Message #${selected.name}`} value={content} />
                  <button className="button primary" disabled={busy || !content.trim()} aria-label="Send message"><Send size={15} /></button>
                </form>
              </>
            ) : (
              <div className="inbox-empty"><Hash size={24} /><p>Create a channel to start team messaging.</p></div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
