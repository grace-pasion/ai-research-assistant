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
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if not value.strip() or value.casefold() in BLOCKED_PASSWORDS:
            raise ValueError("Choose a longer, less common password.")
        if len(set(value)) == 1:
            raise ValueError("A password cannot be the same character repeated.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(APIModel):
    user_id: uuid.UUID
    email: EmailStr
    name: str


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


class ProjectUpdate(BaseModel):
    project_name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)


class ProjectResponse(APIModel):
    project_id: uuid.UUID
    project_name: str
    description: str
    created_at: datetime
    updated_at: datetime


class LatexWorkspaceUpdate(BaseModel):
    main_tex: str = Field(max_length=1_000_000)
    references_bib: str = Field(max_length=500_000)


class LatexWorkspaceResponse(BaseModel):
    main_tex: str
    references_bib: str


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


class PaperSearchResponse(BaseModel):
    query_id: uuid.UUID
    provider: str
    query: str
    results: list[PaperResponse]


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
