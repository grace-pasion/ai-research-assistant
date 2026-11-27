import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, model_validator
from pydantic import field_validator

BLOCKED_PASSWORDS = {
    "123456789012",
    "admin123456",
    "letmein123",
    "password",
    "password123",
    "password123!",
    "qwerty123",
    "welcome1234",
}


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9._-]+$")
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


def validate_password_strength(value: str) -> str:
    if not value.strip() or value.casefold() in BLOCKED_PASSWORDS:
        raise ValueError("Choose a longer, less common password.")
    if len(set(value)) == 1:
        raise ValueError("A password cannot be the same character repeated.")
    return value


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9._-]+$")
    profile_picture: str | None = Field(default=None, max_length=700_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("username")
    @classmethod
    def normalize_profile_username(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value

    @field_validator("profile_picture")
    @classmethod
    def validate_profile_picture(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            media_type, encoded = value.split(",", 1)
            if media_type not in {
                "data:image/jpeg;base64",
                "data:image/png;base64",
                "data:image/webp;base64",
            }:
                raise ValueError("Choose a JPEG, PNG, or WebP profile picture.")
            image = base64.b64decode(encoded, validate=True)
            signatures = {
                "data:image/jpeg;base64": image.startswith(b"\xff\xd8\xff"),
                "data:image/png;base64": image.startswith(b"\x89PNG\r\n\x1a\n"),
                "data:image/webp;base64": (
                    len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP"
                ),
            }
            if not signatures[media_type]:
                raise ValueError("The profile picture is not a valid image.")
        except (ValueError, binascii.Error):
            raise ValueError("The profile picture is not a valid image.") from None
        if not image or len(image) > 512 * 1024:
            raise ValueError("Profile pictures must be smaller than 512 KB.")
        return value


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(APIModel):
    user_id: uuid.UUID
    email: EmailStr
    username: str | None
    name: str
    profile_picture: str | None


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AdminUserSummary(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    name: str
    created_at: datetime
    project_count: int
    document_count: int
    saved_paper_count: int
    conversation_count: int
    last_activity_at: datetime | None


class AdminUserPage(BaseModel):
    users: list[AdminUserSummary]
    total: int
    limit: int
    offset: int


class AdminActivityItem(BaseModel):
    activity_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    action: str
    details: dict
    created_at: datetime


class AdminActivityPage(BaseModel):
    events: list[AdminActivityItem]
    total: int
    limit: int
    offset: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserResponse


class ProjectCreate(BaseModel):
    project_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    team_workspace_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    project_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)


class ProjectResponse(APIModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    team_workspace_id: uuid.UUID | None
    project_name: str
    description: str
    created_at: datetime
    updated_at: datetime
    access_role: Literal["owner", "read", "comment", "edit"] = "owner"


class TeamWorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def normalize_workspace_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Workspace name cannot be blank.")
        return value


class TeamWorkspaceResponse(BaseModel):
    team_workspace_id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    created_at: datetime
    membership_role: Literal["owner", "member"]
    member_count: int


class TeamWorkspaceInvitationCreate(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)


class TeamWorkspaceInvitationResponse(BaseModel):
    invitation_id: uuid.UUID
    team_workspace_id: uuid.UUID
    inviter_id: uuid.UUID
    invitee_id: uuid.UUID
    status: Literal["pending", "accepted", "declined"]
    created_at: datetime
    updated_at: datetime
    workspace_name: str
    inviter_name: str
    invitee_name: str
    invitee_username: str
    invitee_email: EmailStr


class TeamWorkspaceInvitationReply(BaseModel):
    response: Literal["accepted", "declined"]


class TeamWorkspaceMemberResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    name: str
    email: EmailStr
    role: Literal["owner", "member"]
    joined_at: datetime


class TeamChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    project_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_channel_name(cls, value: str) -> str:
        value = value.strip().lstrip("#").strip()
        if not value:
            raise ValueError("Channel name cannot be blank.")
        return value


class TeamChannelResponse(BaseModel):
    channel_id: uuid.UUID
    team_workspace_id: uuid.UUID
    project_id: uuid.UUID | None
    created_by: uuid.UUID
    name: str
    created_at: datetime
    project_name: str | None = None


class TeamChannelMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def normalize_channel_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank.")
        return value


class TeamChannelMessageResponse(BaseModel):
    message_id: uuid.UUID
    channel_id: uuid.UUID
    sender_id: uuid.UUID
    sender_name: str
    content: str
    created_at: datetime


class ProjectInvitationCreate(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    role: Literal["read", "comment", "edit"] = "edit"


class ProjectInvitationRoleUpdate(BaseModel):
    role: Literal["read", "comment", "edit"]


class ProjectInvitationResponse(APIModel):
    invitation_id: uuid.UUID
    project_id: uuid.UUID
    inviter_id: uuid.UUID
    invitee_id: uuid.UUID
    status: Literal["pending", "accepted", "declined"]
    role: Literal["read", "comment", "edit"]
    created_at: datetime
    updated_at: datetime
    invitee_name: str
    invitee_username: str
    invitee_email: EmailStr


class InvitationResponseRequest(BaseModel):
    response: Literal["accepted", "declined"]


class ColleagueResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    name: str
    email: EmailStr


class ProjectCollaboratorResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    name: str
    role: Literal["owner", "read", "comment", "edit"]


class DirectMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank.")
        return value


class DirectMessageResponse(APIModel):
    message_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: uuid.UUID
    content: str
    created_at: datetime
    read_at: datetime | None


class MessageThreadResponse(BaseModel):
    user: ColleagueResponse
    last_message: str
    updated_at: datetime
    unread_count: int


class NotificationResponse(BaseModel):
    notification_id: uuid.UUID
    kind: Literal[
        "project_invitation",
        "invitation_response",
        "message",
        "saved_search_alert",
        "annotation_mention",
        "task_assigned",
    ]
    actor_id: uuid.UUID
    actor_name: str
    actor_username: str | None
    actor_email: EmailStr
    project_id: uuid.UUID | None
    project_name: str | None
    invitation_id: uuid.UUID | None
    invitation_status: Literal["pending", "accepted", "declined"] | None
    invitation_role: Literal["read", "comment", "edit"] | None
    message_id: uuid.UUID | None
    details: dict[str, str | int] = Field(default_factory=dict)
    created_at: datetime
    read_at: datetime | None


class LatexWorkspaceUpdate(BaseModel):
    main_tex: str = Field(max_length=1_000_000)
    references_bib: str = Field(max_length=500_000)
    expected_updated_at: datetime | None = None


class LatexWorkspaceResponse(BaseModel):
    main_tex: str
    references_bib: str
    updated_at: datetime | None = None


class WorkspaceVersionMetadata(BaseModel):
    version_id: uuid.UUID
    filename: str
    version_number: int
    created_at: datetime
    author_name: str | None = None


class WorkspaceRestoreRequest(BaseModel):
    expected_updated_at: datetime | None


class PythonWorkspaceFile(BaseModel):
    filename: str = Field(min_length=4, max_length=128)
    code: str = Field(max_length=100_000)


class PythonWorkspaceUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=100_000)
    files: list[PythonWorkspaceFile] | None = Field(default=None, max_length=20)
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def require_code_or_files(self):
        if self.code is None and self.files is None:
            raise ValueError("Provide Python code or a list of Python files.")
        return self


class PythonArtifactMetadata(BaseModel):
    filename: str
    content_type: str
    byte_size: int
    updated_at: datetime
    script_filename: str | None = None
    input_filenames: list[str] = Field(default_factory=list)


class PythonWorkspaceResponse(BaseModel):
    code: str
    files: list[PythonWorkspaceFile] = Field(default_factory=list)
    updated_at: datetime | None = None
    artifacts: list[PythonArtifactMetadata] = Field(default_factory=list)


class DocumentResponse(APIModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    processing_status: str
    processing_error: str | None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict, validation_alias="custom_metadata")
    uploaded_at: datetime


class LibraryMetadataUpdate(BaseModel):
    tags: list[str] = Field(max_length=30)
    metadata: dict[str, str] = Field(max_length=30)

    @field_validator("tags")
    @classmethod
    def normalize_library_tags(cls, value: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for tag in value:
            tag = tag.strip()
            if not tag:
                raise ValueError("Tags cannot be blank.")
            if len(tag) > 64:
                raise ValueError("Tags must be 64 characters or fewer.")
            if tag.casefold() not in seen:
                normalized.append(tag)
                seen.add(tag.casefold())
        return normalized

    @field_validator("metadata")
    @classmethod
    def normalize_library_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {}
        seen = set()
        for key, metadata_value in value.items():
            key = key.strip()
            metadata_value = metadata_value.strip()
            if not key:
                raise ValueError("Metadata field names cannot be blank.")
            if len(key) > 64 or len(metadata_value) > 500:
                raise ValueError("Metadata field names are limited to 64 characters and values to 500.")
            if key.casefold() in seen:
                raise ValueError("Metadata field names must be unique, ignoring case.")
            normalized[key] = metadata_value
            seen.add(key.casefold())
        return normalized


class LibraryMetadataResponse(BaseModel):
    tags: list[str]
    metadata: dict[str, str]


class BulkDocumentUploadResult(BaseModel):
    filename: str
    document: DocumentResponse | None
    error: str | None


class BulkDocumentUploadResponse(BaseModel):
    results: list[BulkDocumentUploadResult]


class AIUsageResponse(BaseModel):
    assistant_prompts_used: int
    assistant_prompts_limit: int
    assistant_prompts_remaining: int
    embedding_tokens_used: int
    embedding_tokens_limit: int
    embedding_tokens_remaining: int
    resets_at: datetime


class DocumentSearchResult(BaseModel):
    document: DocumentResponse
    excerpt: str


class CrossProjectSearchResult(BaseModel):
    project_id: uuid.UUID
    project_name: str
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID
    title: str
    excerpt: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    tags: list[str] = Field(default_factory=list)


class ProjectCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_collection_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Collection name cannot be blank.")
        return normalized


class ProjectCollectionUpdate(ProjectCollectionCreate):
    pass


class ProjectCollectionItemCreate(BaseModel):
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID


class ProjectCollectionItemResponse(BaseModel):
    item_id: uuid.UUID
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID
    source_title: str | None
    added_at: datetime


class ProjectCollectionResponse(BaseModel):
    collection_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    items: list[ProjectCollectionItemResponse] = Field(default_factory=list)


class DocumentReaderResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    text: str


class AnnotationCreate(BaseModel):
    quote: str | None = Field(default=None, max_length=20000)
    note: str = Field(default="", max_length=5000)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @field_validator("note")
    @classmethod
    def normalize_annotation_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_annotation_content(self):
        if not self.note and not (self.quote and self.quote.strip()):
            raise ValueError("Add a note or select text to highlight.")
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("Both selection offsets are required.")
        if self.start_offset is not None:
            if not self.quote or self.end_offset - self.start_offset != len(self.quote):
                raise ValueError("Selection offsets must match the highlighted text.")
        return self


class AnnotationSourceLink(BaseModel):
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID


class AnnotationUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=20)
    is_pinned: bool | None = None
    related_sources: list[AnnotationSourceLink] | None = Field(default=None, max_length=20)

    @field_validator("note")
    @classmethod
    def normalize_annotation_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("tags")
    @classmethod
    def normalize_annotation_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            tag = tag.strip()
            if not tag:
                continue
            if len(tag) > 32:
                raise ValueError("Tags must be 32 characters or fewer.")
            key = tag.casefold()
            if key not in seen:
                normalized.append(tag)
                seen.add(key)
        return normalized

    @model_validator(mode="after")
    def validate_annotation_update(self):
        if not any(
            getattr(self, field) is not None
            for field in ("note", "tags", "is_pinned", "related_sources")
        ):
            raise ValueError("Provide at least one note field to update.")
        return self


class AnnotationResponse(APIModel):
    annotation_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    quote: str | None
    note: str
    tags: list[str] = Field(default_factory=list)
    is_pinned: bool = False
    related_sources: list[AnnotationSourceLink] = Field(default_factory=list)
    author_id: uuid.UUID | None = Field(
        validation_alias=AliasChoices("author_id", "created_by")
    )
    author_name: str | None
    start_offset: int | None
    end_offset: int | None
    created_at: datetime
    updated_at: datetime


class ProjectAnnotationResponse(AnnotationResponse):
    source_type: Literal["document", "paper"]
    source_title: str


class ProjectTaskCreate(BaseModel):
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID
    annotation_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    assignee_id: uuid.UUID

    @field_validator("title")
    @classmethod
    def normalize_task_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Task title cannot be blank.")
        return value


class ProjectTaskUpdate(BaseModel):
    status: Literal["open", "in_progress", "done"] | None = None
    assignee_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.status is None and "assignee_id" not in self.model_fields_set:
            raise ValueError("Provide a task status or assignee update.")
        return self


class ProjectTaskResponse(APIModel):
    task_id: uuid.UUID
    project_id: uuid.UUID
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID
    source_title: str
    annotation_id: uuid.UUID | None
    title: str
    status: Literal["open", "in_progress", "done"]
    created_by: uuid.UUID
    created_by_name: str
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    assignee_username: str | None
    created_at: datetime
    updated_at: datetime


class ProjectActivityResponse(BaseModel):
    activity_id: uuid.UUID
    action: str
    actor_name: str | None
    created_at: datetime


class PaperAuthorResponse(BaseModel):
    author_id: uuid.UUID
    author_name: str


ScreeningExclusionReason = Literal[
    "wrong_population",
    "wrong_intervention",
    "wrong_comparator",
    "wrong_outcome",
    "wrong_study_design",
    "wrong_setting",
    "wrong_publication_type",
    "duplicate_record",
    "full_text_unavailable",
    "other",
]


def _validate_exclusion_fields(
    screening_status: str,
    exclusion_reason: str | None,
    screening_note: str,
) -> None:
    if screening_status == "exclude" and exclusion_reason is None:
        raise ValueError("Choose a structured reason when excluding a paper.")
    if screening_status != "exclude" and exclusion_reason is not None:
        raise ValueError("An exclusion reason can only be set for excluded papers.")
    if exclusion_reason == "other" and not screening_note.strip():
        raise ValueError("Add a note when the exclusion reason is Other.")


class PaperScreeningDecisionResponse(BaseModel):
    user_id: uuid.UUID
    user_name: str
    screening_status: Literal["undecided", "include", "exclude"]
    exclusion_reason: ScreeningExclusionReason | None
    screening_note: str
    created_at: datetime
    updated_at: datetime


class PaperScreeningAssignmentResponse(BaseModel):
    user_id: uuid.UUID
    user_name: str
    username: str | None
    assigned_at: datetime


class PaperStudyExtractionResponse(APIModel):
    population: str
    methods: str
    sample_size: str
    outcomes: str
    limitations: str
    updated_by: uuid.UUID | None
    updated_by_name: str | None
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def assume_utc_for_naive_timestamp(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class PaperResponse(BaseModel):
    paper_id: uuid.UUID
    external_paper_id: str
    api_provider: str
    title: str
    abstract: str | None
    publication_year: int | None
    doi: str | None
    paper_url: str | None
    venue: str | None
    citation_count: int | None
    authors: list[PaperAuthorResponse] = Field(default_factory=list)
    saved: bool = False
    screening_status: Literal["unread", "undecided", "include", "exclude"] = "unread"
    screening_note: str = ""
    screening_exclusion_reason: ScreeningExclusionReason | None = None
    screening_decisions: list[PaperScreeningDecisionResponse] = Field(default_factory=list)
    screening_assignments: list[PaperScreeningAssignmentResponse] = Field(default_factory=list)
    screening_disagreement: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    study_extraction: PaperStudyExtractionResponse | None = None


class PaperStudyExtractionUpdate(BaseModel):
    population: str = Field(default="", max_length=10_000)
    methods: str = Field(default="", max_length=10_000)
    sample_size: str = Field(default="", max_length=2_000)
    outcomes: str = Field(default="", max_length=10_000)
    limitations: str = Field(default="", max_length=10_000)
    expected_updated_at: datetime | None

    @field_validator("population", "methods", "sample_size", "outcomes", "limitations")
    @classmethod
    def normalize_extraction_text(cls, value: str) -> str:
        return value.strip()


class PaperScreeningUpdate(BaseModel):
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str = Field(default="", max_length=500)
    exclusion_reason: ScreeningExclusionReason | None = None

    @field_validator("screening_note")
    @classmethod
    def normalize_screening_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_exclusion(self):
        _validate_exclusion_fields(
            self.screening_status, self.exclusion_reason, self.screening_note
        )
        return self


class PaperScreeningResponse(BaseModel):
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str
    exclusion_reason: ScreeningExclusionReason | None


class PaperScreeningDecisionUpdate(BaseModel):
    screening_status: Literal["undecided", "include", "exclude"]
    exclusion_reason: ScreeningExclusionReason | None = None
    screening_note: str = Field(default="", max_length=500)

    @field_validator("screening_note")
    @classmethod
    def normalize_screening_decision_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_exclusion(self):
        _validate_exclusion_fields(
            self.screening_status, self.exclusion_reason, self.screening_note
        )
        return self


class PaperScreeningAssignmentsUpdate(BaseModel):
    user_ids: list[uuid.UUID]

    @field_validator("user_ids")
    @classmethod
    def reject_duplicate_assignees(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("A collaborator can only be assigned once to a paper.")
        return value


class PaperScreeningBulkUpdate(BaseModel):
    paper_ids: list[uuid.UUID] = Field(min_length=1)
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str | None = Field(default=None, max_length=500)
    exclusion_reason: ScreeningExclusionReason | None = None

    @field_validator("screening_note")
    @classmethod
    def normalize_screening_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_exclusion(self):
        _validate_exclusion_fields(
            self.screening_status, self.exclusion_reason, self.screening_note or ""
        )
        return self


class PaperScreeningBulkResponse(BaseModel):
    updated_count: int


class SystematicReviewUpdate(BaseModel):
    review_question: str = Field(max_length=2_000)
    protocol: str = Field(max_length=20_000)
    expected_updated_at: datetime | None

    @field_validator("review_question", "protocol")
    @classmethod
    def normalize_review_text(cls, value: str) -> str:
        return value.strip()


class PaperScreeningCounts(BaseModel):
    total: int
    unread: int
    undecided: int
    include: int
    exclude: int
    reviewed: int


class SystematicReviewResponse(BaseModel):
    review_question: str
    protocol: str
    updated_at: datetime | None
    screening_counts: PaperScreeningCounts


class ProjectSourceSummaryRequest(BaseModel):
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID


class ProjectSourceSummaryResponse(BaseModel):
    source_type: Literal["document", "paper"]
    source_id: uuid.UUID
    title: str
    summary: str
    updated_at: datetime
    cached: bool


class SearchRecordResponse(APIModel):
    searched_at: datetime

    @field_validator("searched_at")
    @classmethod
    def assume_utc_for_naive_timestamp(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class PaperSearchResponse(SearchRecordResponse):
    query_id: uuid.UUID
    provider: str
    query: str
    filters: dict[str, str | int]
    result_count: int
    results: list[PaperResponse]


class SearchQueryHistoryResponse(SearchRecordResponse):
    query_id: uuid.UUID
    query_text: str
    api_provider: str
    search_filters: dict[str, str | int]
    result_count: int


class CrossProjectSearchRecordResponse(SearchRecordResponse):
    record_id: uuid.UUID
    query_text: str
    provider: str
    filters: dict[str, str | int]
    result_count: int


class SavedPaperSearchCreate(BaseModel):
    query_id: uuid.UUID
    alert_enabled: bool = False


class SavedPaperSearchUpdate(BaseModel):
    alert_enabled: bool


class SavedPaperSearchResponse(APIModel):
    saved_search_id: uuid.UUID
    project_id: uuid.UUID
    query_text: str
    api_provider: str
    alert_enabled: bool
    last_checked_at: datetime | None
    created_at: datetime


class SavedPaperSearchRunResponse(PaperSearchResponse):
    new_result_count: int


class SavedPaperSearchAlertsCheckResponse(BaseModel):
    checked_count: int
    notifications_created: int


class PaperImportResult(BaseModel):
    paper_id: uuid.UUID
    title: str
    doi: str | None
    status: Literal["imported", "matched", "duplicate"]


class PaperImportResponse(BaseModel):
    added_count: int
    duplicate_count: int
    results: list[PaperImportResult]


class AssistantSourceSelection(BaseModel):
    document_ids: list[uuid.UUID] = Field(max_length=200)
    paper_ids: list[uuid.UUID] = Field(max_length=200)

    @model_validator(mode="after")
    def require_sources(self):
        if not self.document_ids and not self.paper_ids:
            raise ValueError("Select at least one project source.")
        return self


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=5000)
    mode: Literal["question", "compare", "directions"] = "question"
    conversation_id: uuid.UUID | None = None
    source_selection: AssistantSourceSelection | None = None


class SourceResponse(BaseModel):
    kind: Literal["document", "paper"]
    source_id: uuid.UUID
    title: str
    excerpt: str
    document_id: uuid.UUID | None = None
    page_number: int | None = None
    paper_id: uuid.UUID | None = None
    paper_url: str | None = None


class AssistantDraftResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    approval_token: str
    review_required: Literal[True] = True
    message: str = "Review this answer. Nothing has been saved yet."


class ApproveRequest(BaseModel):
    approval_token: str


class ConversationSummaryResponse(APIModel):
    conversation_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(APIModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    reviewed: bool
    sources: list[SourceResponse] = []


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: list[ConversationMessageResponse]
