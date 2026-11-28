import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ResearchBase(DeclarativeBase):
    pass


class LiteratureBase(DeclarativeBase):
    pass


def uuid_column():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(ResearchBase):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = uuid_column()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    profile_picture: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserActivity(ResearchBase):
    __tablename__ = "user_activity"

    activity_id: Mapped[uuid.UUID] = uuid_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectActivity(ResearchBase):
    __tablename__ = "project_activities"
    __table_args__ = (
        Index("ix_project_activities_project_created", "project_id", "created_at"),
    )

    activity_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthRateLimit(ResearchBase):
    __tablename__ = "auth_rate_limits"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DailyPromptUsage(ResearchBase):
    __tablename__ = "daily_prompt_usage"

    client_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    prompt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DailyEmbeddingUsage(ResearchBase):
    __tablename__ = "daily_embedding_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TeamWorkspace(ResearchBase):
    __tablename__ = "team_workspaces"

    team_workspace_id: Mapped[uuid.UUID] = uuid_column()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamWorkspaceMembership(ResearchBase):
    __tablename__ = "team_workspace_memberships"
    __table_args__ = (UniqueConstraint("team_workspace_id", "user_id"),)

    membership_id: Mapped[uuid.UUID] = uuid_column()
    team_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_workspaces.team_workspace_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamWorkspaceInvitation(ResearchBase):
    __tablename__ = "team_workspace_invitations"
    __table_args__ = (UniqueConstraint("team_workspace_id", "invitee_id"),)

    invitation_id: Mapped[uuid.UUID] = uuid_column()
    team_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_workspaces.team_workspace_id", ondelete="CASCADE"), index=True
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    invitee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResearchProject(ResearchBase):
    __tablename__ = "research_projects"
    __table_args__ = (Index("ix_projects_owner_updated", "user_id", "updated_at"),)

    project_id: Mapped[uuid.UUID] = uuid_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    team_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("team_workspaces.team_workspace_id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeamChannel(ResearchBase):
    __tablename__ = "team_channels"
    __table_args__ = (UniqueConstraint("team_workspace_id", "name"),)

    channel_id: Mapped[uuid.UUID] = uuid_column()
    team_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_workspaces.team_workspace_id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamChannelMessage(ResearchBase):
    __tablename__ = "team_channel_messages"

    message_id: Mapped[uuid.UUID] = uuid_column()
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_channels.channel_id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectInvitation(ResearchBase):
    __tablename__ = "project_invitations"
    __table_args__ = (UniqueConstraint("project_id", "invitee_id"),)

    invitation_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    inviter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    invitee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="edit")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DirectMessage(ResearchBase):
    __tablename__ = "direct_messages"

    message_id: Mapped[uuid.UUID] = uuid_column()
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(ResearchBase):
    __tablename__ = "notifications"

    notification_id: Mapped[uuid.UUID] = uuid_column()
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), nullable=True, index=True
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_invitations.invitation_id", ondelete="CASCADE"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("direct_messages.message_id", ondelete="CASCADE"), nullable=True
    )
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationPreference(ResearchBase):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    project_invitations: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    invitation_responses: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    direct_messages: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    saved_search_alerts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    annotation_mentions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    task_assignments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class LatexWorkspace(ResearchBase):
    __tablename__ = "latex_workspaces"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), primary_key=True
    )
    main_tex: Mapped[str] = mapped_column(Text, nullable=False)
    references_bib: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectFileVersion(ResearchBase):
    __tablename__ = "project_file_versions"
    __table_args__ = (
        CheckConstraint("workspace_type IN ('latex', 'python')"),
        UniqueConstraint(
            "project_id",
            "workspace_type",
            "filename",
            "version_number",
        ),
    )

    version_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE")
    )
    workspace_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PythonWorkspace(ResearchBase):
    __tablename__ = "python_workspaces"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    files: Mapped[list[dict[str, str]] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PythonAnalysisRun(ResearchBase):
    __tablename__ = "python_analysis_runs"

    run_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    script_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    source_files: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    input_files: Mapped[list[dict[str, str | int]]] = mapped_column(JSON, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )


class PythonWorkspaceArtifact(ResearchBase):
    __tablename__ = "python_workspace_artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "filename"),
        Index("ix_python_workspace_artifacts_project", "project_id"),
        Index("ix_python_workspace_artifacts_run", "run_id"),
    )

    artifact_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    script_filename: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_filenames: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("python_analysis_runs.run_id", ondelete="SET NULL"), nullable=True
    )
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index(
    "uq_python_workspace_artifacts_project_filename_ci",
    PythonWorkspaceArtifact.project_id,
    func.lower(PythonWorkspaceArtifact.filename),
    unique=True,
)


class Document(ResearchBase):
    __tablename__ = "documents"

    document_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    custom_metadata: Mapped[dict[str, str]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Annotation(ResearchBase):
    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(
            "(document_id IS NOT NULL AND paper_id IS NULL) OR "
            "(document_id IS NULL AND paper_id IS NOT NULL)",
            name="ck_annotations_single_target",
        ),
        CheckConstraint(
            "length(trim(note)) > 0 OR (quote IS NOT NULL AND length(trim(quote)) > 0)",
            name="ck_annotations_content",
        ),
    )

    annotation_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=True, index=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    quote: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    related_sources: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    author: Mapped[User | None] = relationship(foreign_keys=[created_by])

    @property
    def author_name(self) -> str | None:
        return self.author.name if self.author is not None else None


class ProjectTask(ResearchBase):
    __tablename__ = "project_tasks"
    __table_args__ = (
        CheckConstraint(
            "(document_id IS NOT NULL AND paper_id IS NULL) OR "
            "(document_id IS NULL AND paper_id IS NOT NULL)",
            name="ck_project_tasks_single_source",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'done')",
            name="ck_project_tasks_status",
        ),
    )

    task_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=True, index=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    annotation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("annotations.annotation_id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentChunk(ResearchBase):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index(
            "ix_document_chunks_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: Mapped[uuid.UUID] = uuid_column()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    token_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(ResearchBase):
    __tablename__ = "conversations"

    conversation_id: Mapped[uuid.UUID] = uuid_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(ResearchBase):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("approval_id"),)

    message_id: Mapped[uuid.UUID] = uuid_column()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MessageChunkSource(ResearchBase):
    __tablename__ = "message_chunk_sources"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.message_id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    source_order: Mapped[int] = mapped_column(Integer)


class MessagePaperSource(ResearchBase):
    __tablename__ = "message_paper_sources"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.message_id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_order: Mapped[int] = mapped_column(Integer)


class SearchQuery(ResearchBase):
    __tablename__ = "search_queries"

    query_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[str] = mapped_column(Text)
    api_provider: Mapped[str] = mapped_column(String(32))
    search_filters: Mapped[dict[str, str | int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrossProjectSearchRecord(ResearchBase):
    __tablename__ = "cross_project_search_records"

    record_id: Mapped[uuid.UUID] = uuid_column()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), default="project_library")
    filters: Mapped[dict[str, str | int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchQueryResult(ResearchBase):
    __tablename__ = "search_query_results"

    query_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_queries.query_id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    relevance_score: Mapped[float | None] = mapped_column(Float)


class SavedPaperSearch(ResearchBase):
    __tablename__ = "saved_paper_searches"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "query_text", "api_provider"),
    )

    saved_search_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[str] = mapped_column(Text)
    api_provider: Mapped[str] = mapped_column(String(32))
    alert_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seen_external_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_new_result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectPaper(ResearchBase):
    __tablename__ = "project_papers"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    relationship_type: Mapped[str] = mapped_column(String(64), default="saved")
    screening_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unread", server_default="unread"
    )
    screening_note: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    screening_exclusion_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    custom_metadata: Mapped[dict[str, str]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectCollection(ResearchBase):
    __tablename__ = "project_collections"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "normalized_name",
            name="uq_project_collections_project_name",
        ),
    )

    collection_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectCollectionItem(ResearchBase):
    __tablename__ = "project_collection_items"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'document' AND document_id IS NOT NULL AND paper_id IS NULL) OR "
            "(source_type = 'paper' AND paper_id IS NOT NULL AND document_id IS NULL)",
            name="ck_project_collection_items_single_source",
        ),
        Index(
            "uq_collection_document_item",
            "collection_id",
            "document_id",
            unique=True,
            sqlite_where=text("document_id IS NOT NULL"),
            postgresql_where=text("document_id IS NOT NULL"),
        ),
        Index(
            "uq_collection_paper_item",
            "collection_id",
            "paper_id",
            unique=True,
            sqlite_where=text("paper_id IS NOT NULL"),
            postgresql_where=text("paper_id IS NOT NULL"),
        ),
    )

    item_id: Mapped[uuid.UUID] = uuid_column()
    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_collections.collection_id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperScreeningDecision(ResearchBase):
    __tablename__ = "paper_screening_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "paper_id"],
            ["project_papers.project_id", "project_papers.paper_id"],
            ondelete="CASCADE",
        ),
        Index("ix_screening_decisions_project_paper", "project_id", "paper_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    screening_status: Mapped[str] = mapped_column(String(16), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    screening_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperScreeningAssignment(ResearchBase):
    __tablename__ = "paper_screening_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "paper_id"],
            ["project_papers.project_id", "project_papers.paper_id"],
            ondelete="CASCADE",
        ),
        Index("ix_paper_screening_assignments_project_user", "project_id", "user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperStudyExtraction(ResearchBase):
    __tablename__ = "paper_study_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "paper_id"],
            ["project_papers.project_id", "project_papers.paper_id"],
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    population: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    methods: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sample_size: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    outcomes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    limitations: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SystematicReviewWorkspace(ResearchBase):
    __tablename__ = "systematic_review_workspaces"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), primary_key=True
    )
    review_question: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    protocol: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectSourceSummary(ResearchBase):
    __tablename__ = "project_source_summaries"
    __table_args__ = (UniqueConstraint("project_id", "source_type", "source_id"),)

    summary_id: Mapped[uuid.UUID] = uuid_column()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_projects.project_id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentPaper(ResearchBase):
    __tablename__ = "document_papers"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    relationship_type: Mapped[str] = mapped_column(String(64), default="related")


class Paper(LiteratureBase):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("api_provider", "external_paper_id"),)

    paper_id: Mapped[uuid.UUID] = uuid_column()
    external_paper_id: Mapped[str] = mapped_column(String(255))
    api_provider: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(255), index=True)
    paper_url: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(String(512))
    citation_count: Mapped[int | None] = mapped_column(Integer)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Author(LiteratureBase):
    __tablename__ = "authors"
    __table_args__ = (UniqueConstraint("api_provider", "external_author_id"),)

    author_id: Mapped[uuid.UUID] = uuid_column()
    author_name: Mapped[str] = mapped_column(String(255))
    external_author_id: Mapped[str] = mapped_column(String(255))
    api_provider: Mapped[str] = mapped_column(String(32))


class PaperAuthor(LiteratureBase):
    __tablename__ = "paper_authors"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.paper_id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.author_id", ondelete="CASCADE"), primary_key=True
    )
    author_order: Mapped[int] = mapped_column(Integer)
