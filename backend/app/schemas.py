import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic import field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(APIModel):
    user_id: uuid.UUID
    email: EmailStr
    name: str


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


class DocumentResponse(APIModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    file_type: str
    file_size: int
    processing_status: str
    processing_error: str | None
    uploaded_at: datetime


class DocumentSearchResult(BaseModel):
    document: DocumentResponse
    excerpt: str


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


class PaperSearchResponse(BaseModel):
    query_id: uuid.UUID
    provider: str
    query: str
    results: list[PaperResponse]


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
    paper_id: uuid.UUID | None = None


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
