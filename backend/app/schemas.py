import base64
import binascii
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
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


class ProjectInvitationResponse(APIModel):
    invitation_id: uuid.UUID
    project_id: uuid.UUID
    inviter_id: uuid.UUID
    invitee_id: uuid.UUID
    status: Literal["pending", "accepted", "declined"]
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
    kind: Literal["project_invitation", "invitation_response", "message", "saved_search_alert"]
    actor_id: uuid.UUID
    actor_name: str
    actor_username: str | None
    actor_email: EmailStr
    project_id: uuid.UUID | None
    project_name: str | None
    invitation_id: uuid.UUID | None
    invitation_status: Literal["pending", "accepted", "declined"] | None
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


class DocumentResponse(APIModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    processing_status: str
    processing_error: str | None
    uploaded_at: datetime


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


class AnnotationUpdate(BaseModel):
    note: str = Field(max_length=5000)

    @field_validator("note")
    @classmethod
    def normalize_annotation_note(cls, value: str) -> str:
        return value.strip()


class AnnotationResponse(APIModel):
    annotation_id: uuid.UUID
    project_id: uuid.UUID
    document_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    quote: str | None
    note: str
    start_offset: int | None
    end_offset: int | None
    created_at: datetime
    updated_at: datetime


class PaperAuthorResponse(BaseModel):
    author_id: uuid.UUID
    author_name: str


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
    authors: list[PaperAuthorResponse] = []
    saved: bool = False
    screening_status: Literal["unread", "undecided", "include", "exclude"] = "unread"
    screening_note: str = ""


class PaperScreeningUpdate(BaseModel):
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str = Field(default="", max_length=500)

    @field_validator("screening_note")
    @classmethod
    def normalize_screening_note(cls, value: str) -> str:
        return value.strip()


class PaperScreeningResponse(BaseModel):
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str


class PaperScreeningBulkUpdate(BaseModel):
    paper_ids: list[uuid.UUID] = Field(min_length=1)
    screening_status: Literal["unread", "undecided", "include", "exclude"]
    screening_note: str | None = Field(default=None, max_length=500)

    @field_validator("screening_note")
    @classmethod
    def normalize_screening_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class PaperScreeningBulkResponse(BaseModel):
    updated_count: int


class PaperSearchResponse(BaseModel):
    query_id: uuid.UUID
    provider: str
    query: str
    results: list[PaperResponse]


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


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=5000)
    mode: Literal["question", "compare", "directions"] = "question"
    conversation_id: uuid.UUID | None = None


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
