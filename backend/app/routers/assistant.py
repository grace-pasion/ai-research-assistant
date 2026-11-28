import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, get_literature_db
from app.models import (
    Conversation,
    Document,
    DocumentChunk,
    Author,
    Message,
    MessageChunkSource,
    MessagePaperSource,
    Paper,
    PaperAuthor,
    ProjectPaper,
    User,
)
from app.schemas import (
    AssistantDraftResponse,
    AskRequest,
    ApproveRequest,
    ConversationDetailResponse,
    ConversationMessageResponse,
    ConversationSummaryResponse,
    ConversationTitleUpdate,
    RetryDraftRequest,
    SourceResponse,
)
from app.security import get_current_user, require_project_access
from app.services.assistant import draft_answer
from app.services.audit import record_activity
from app.services.rate_limit import consume_daily_prompt
from app.services.research_brief import (
    BriefSource,
    citation_indices,
    create_research_brief,
    parse_evidence_matrix,
)

router = APIRouter(prefix="/api/projects/{project_id}/assistant", tags=["research assistant"])
APPROVAL_SALT = "approved-research-answer-v1"


def _approval_serializer() -> URLSafeTimedSerializer:
    secret = get_settings().jwt_secret.get_secret_value()
    return URLSafeTimedSerializer(secret, salt=APPROVAL_SALT)


def _load_approval_draft(
    approval_token: str, user_id: uuid.UUID, project_id: uuid.UUID
) -> dict[str, Any]:
    try:
        draft = _approval_serializer().loads(
            approval_token,
            max_age=get_settings().approval_token_max_age_seconds,
        )
    except SignatureExpired:
        raise HTTPException(
            status_code=400,
            detail="This review expired. Generate a fresh answer and approve it within 15 minutes.",
        ) from None
    except BadSignature:
        raise HTTPException(status_code=400, detail="Invalid approval token.") from None
    if draft.get("user_id") != str(user_id) or draft.get("project_id") != str(project_id):
        raise HTTPException(status_code=403, detail="This review belongs to a different user or project.")
    return draft


def _assistant_draft_response(
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    question: str,
    mode: str,
    conversation_id: uuid.UUID | None,
    answer: str,
    sources: list[dict],
) -> AssistantDraftResponse:
    approval_payload = {
        "user_id": str(user_id),
        "project_id": str(project_id),
        "question": question,
        "answer": answer,
        "mode": mode,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "sources": [
            {"kind": source["kind"], "id": str(source["source_id"])} for source in sources
        ],
    }
    return AssistantDraftResponse(
        answer=answer,
        sources=[SourceResponse(**source) for source in sources],
        approval_token=_approval_serializer().dumps(approval_payload),
    )


def _conversation_for_user(
    db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID, project_id: uuid.UUID
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.project_id == project_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


def _conversation_detail(
    db: Session,
    literature_db: Session,
    conversation: Conversation,
    messages: list[Message],
) -> ConversationDetailResponse:
    from app.models import Author, Paper, PaperAuthor

    details = []
    for message in messages:
        ordered_sources: list[tuple[int, SourceResponse]] = []
        if message.role == "assistant":
            document_sources = db.execute(
                select(MessageChunkSource.source_order, DocumentChunk, Document)
                .join(
                    DocumentChunk,
                    DocumentChunk.chunk_id == MessageChunkSource.chunk_id,
                )
                .join(Document, Document.document_id == DocumentChunk.document_id)
                .where(MessageChunkSource.message_id == message.message_id)
            ).all()
            ordered_sources.extend(
                (
                    source_order,
                    SourceResponse(
                        kind="document",
                        source_id=chunk.chunk_id,
                        title=document.filename,
                        excerpt=chunk.chunk_text[:1800],
                        document_id=document.document_id,
                        page_number=chunk.page_number,
                    ),
                )
                for source_order, chunk, document in document_sources
            )
            paper_sources = db.execute(
                select(MessagePaperSource.source_order, MessagePaperSource.paper_id).where(
                    MessagePaperSource.message_id == message.message_id
                )
            ).all()
            for source_order, paper_id in paper_sources:
                paper = literature_db.get(Paper, paper_id)
                if paper is None:
                    continue
                author_names = literature_db.scalars(
                    select(Author.author_name)
                    .join(PaperAuthor, PaperAuthor.author_id == Author.author_id)
                    .where(PaperAuthor.paper_id == paper_id)
                    .order_by(PaperAuthor.author_order)
                ).all()
                title = paper.title
                if paper.publication_year:
                    title = f"{title} ({paper.publication_year})"
                if author_names:
                    title += f" — {', '.join(author_names[:4])}"
                ordered_sources.append(
                    (
                        source_order,
                        SourceResponse(
                            kind="paper",
                            source_id=paper.paper_id,
                            title=title,
                            excerpt=(paper.abstract or "No abstract is available.")[:1400],
                            paper_id=paper.paper_id,
                            paper_url=paper.paper_url,
                        ),
                    )
                )
        details.append(
            ConversationMessageResponse(
                message_id=message.message_id,
                conversation_id=message.conversation_id,
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                reviewed=message.reviewed,
                sources=[source for _, source in sorted(ordered_sources, key=lambda item: item[0])],
            )
        )
    return ConversationDetailResponse(
        conversation_id=conversation.conversation_id,
        project_id=conversation.project_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=details,
    )


def _approved_response(
    db: Session,
    literature_db: Session,
    approval_id: str,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ConversationDetailResponse | None:
    existing_message = db.scalar(select(Message).where(Message.approval_id == approval_id))
    if existing_message is None:
        return None
    conversation = _conversation_for_user(
        db, existing_message.conversation_id, user_id, project_id
    )
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    return _conversation_detail(db, literature_db, conversation, messages)


def _commit_approval(
    db: Session,
    literature_db: Session,
    approval_id: str,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ConversationDetailResponse | None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_response = _approved_response(
            db, literature_db, approval_id, user_id, project_id
        )
        if existing_response is None:
            raise
        return existing_response
    return None


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    return list(
        db.scalars(
            select(Conversation)
            .where(
                Conversation.project_id == project_id,
                Conversation.user_id == user.user_id,
            )
            .order_by(Conversation.updated_at.desc())
        ).all()
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSummaryResponse,
)
def rename_conversation(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: ConversationTitleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    conversation = _conversation_for_user(db, conversation_id, user.user_id, project_id)
    conversation.title = payload.title
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    conversation = _conversation_for_user(db, conversation_id, user.user_id, project_id)
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    return _conversation_detail(db, literature_db, conversation, messages)


@router.get("/conversations/{conversation_id}/brief")
def export_research_brief(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    conversation = _conversation_for_user(db, conversation_id, user.user_id, project_id)
    message = db.scalar(
        select(Message).where(
            Message.message_id == message_id,
            Message.conversation_id == conversation_id,
            Message.role == "assistant",
            Message.reviewed.is_(True),
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Approved assistant response not found.")
    question = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "user",
            Message.created_at < message.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if question is None:
        raise HTTPException(status_code=409, detail="The research question for this response is unavailable.")
    try:
        matrix_rows = parse_evidence_matrix(message.content)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="Brief export is available for approved Compare sources responses.",
        ) from exc

    message_details = _conversation_detail(db, literature_db, conversation, [message]).messages[0]
    sources = message_details.sources
    if len(matrix_rows) != len(sources) or not sources:
        raise HTTPException(
            status_code=409,
            detail="A cited source is no longer available; generate a new comparison before exporting.",
        )
    for row in matrix_rows:
        citations = citation_indices(*row.cells())
        if (
            not citation_indices(row.citations)
            or not citations
            or any(source_index < 1 or source_index > len(sources) for source_index in citations)
        ):
            raise HTTPException(
                status_code=409,
                detail="A cited source is no longer available; generate a new comparison before exporting.",
            )

    brief_sources = []
    for source_index, source in enumerate(sources, start=1):
        if source.kind == "paper":
            paper = literature_db.get(Paper, source.paper_id)
            if paper is None:
                raise HTTPException(
                    status_code=409,
                    detail="A cited source is no longer available; generate a new comparison before exporting.",
                )
            authors = literature_db.scalars(
                select(Author.author_name)
                .join(PaperAuthor, PaperAuthor.author_id == Author.author_id)
                .where(PaperAuthor.paper_id == paper.paper_id)
                .order_by(PaperAuthor.author_order)
            ).all()
            brief_sources.append(
                BriefSource(
                    index=source_index,
                    kind="paper",
                    title=paper.title,
                    authors=tuple(authors),
                    year=paper.publication_year,
                    venue=paper.venue,
                    doi=paper.doi,
                    url=paper.paper_url,
                )
            )
        else:
            brief_sources.append(
                BriefSource(
                    index=source_index,
                    kind="document",
                    title=source.title,
                    page_number=source.page_number,
                )
            )

    content = create_research_brief(
        conversation.title,
        question.content,
        matrix_rows,
        brief_sources,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="research-brief.docx"'},
    )


@router.post("/draft", response_model=AssistantDraftResponse)
def create_draft(
    project_id: uuid.UUID,
    payload: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    if payload.conversation_id is not None:
        _conversation_for_user(db, payload.conversation_id, user.user_id, project_id)
    selection = payload.source_selection
    if selection is not None:
        document_ids = set(selection.document_ids)
        paper_ids = set(selection.paper_ids)
        available_documents = set(db.scalars(
            select(Document.document_id).where(
                Document.project_id == project_id,
                Document.processing_status == "ready",
                Document.document_id.in_(document_ids),
            )
        ).all())
        available_papers = set(db.scalars(
            select(ProjectPaper.paper_id).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.paper_id.in_(paper_ids),
            )
        ).all())
        if document_ids != available_documents or paper_ids != available_papers:
            raise HTTPException(
                status_code=422,
                detail="A selected source is unavailable in this project. Refresh and select sources again.",
            )
    consume_daily_prompt(db, request)
    record_activity(db, user.user_id, "assistant.draft_requested", {"mode": payload.mode})
    db.commit()
    args = (db, literature_db, project_id, payload.question.strip(), payload.mode, payload.conversation_id)
    if selection is None:
        answer, sources = draft_answer(*args)
    else:
        answer, sources = draft_answer(
            *args,
            document_ids=set(selection.document_ids),
            paper_ids=set(selection.paper_ids),
        )
    return _assistant_draft_response(
        user.user_id,
        project_id,
        payload.question.strip(),
        payload.mode,
        payload.conversation_id,
        answer,
        sources,
    )


@router.post("/draft/retry", response_model=AssistantDraftResponse)
def retry_draft(
    project_id: uuid.UUID,
    payload: RetryDraftRequest,
    request: Request,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    draft = _load_approval_draft(payload.approval_token, user.user_id, project_id)
    require_project_access(db, project_id, user.user_id)

    conversation_id = uuid.UUID(draft["conversation_id"]) if draft.get("conversation_id") else None
    if conversation_id is not None:
        _conversation_for_user(db, conversation_id, user.user_id, project_id)

    question = draft.get("question")
    mode = draft.get("mode")
    source_data = draft.get("sources")
    if (
        not isinstance(question, str)
        or not question.strip()
        or mode not in ("question", "compare", "directions")
        or not isinstance(source_data, list)
        or not source_data
    ):
        raise HTTPException(status_code=400, detail="This review cannot be retried.")

    source_refs: list[tuple[str, uuid.UUID]] = []
    for source in source_data:
        if not isinstance(source, dict) or source.get("kind") not in ("document", "paper"):
            raise HTTPException(status_code=400, detail="Invalid approval token.")
        try:
            source_id = uuid.UUID(source["id"])
        except (AttributeError, KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid approval token.") from None
        source_refs.append((source["kind"], source_id))
    source_refs = list(dict.fromkeys(source_refs))
    chunk_ids = {source_id for kind, source_id in source_refs if kind == "document"}
    paper_ids = {source_id for kind, source_id in source_refs if kind == "paper"}

    available_chunk_ids = set()
    if chunk_ids:
        available_chunk_ids = set(
            db.scalars(
                select(DocumentChunk.chunk_id)
                .join(Document, Document.document_id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.chunk_id.in_(chunk_ids),
                    Document.project_id == project_id,
                    Document.processing_status == "ready",
                )
            ).all()
        )
    available_paper_ids = set()
    if paper_ids:
        available_paper_ids = set(
            literature_db.scalars(
                select(Paper.paper_id).where(Paper.paper_id.in_(paper_ids))
            ).all()
        )
    if available_chunk_ids != chunk_ids or available_paper_ids != paper_ids:
        raise HTTPException(
            status_code=409,
            detail="A source in this draft is no longer available. Generate a fresh answer to continue.",
        )

    consume_daily_prompt(db, request)
    record_activity(db, user.user_id, "assistant.draft_requested", {"mode": mode})
    db.commit()
    answer, sources = draft_answer(
        db,
        literature_db,
        project_id,
        question.strip(),
        mode,
        conversation_id,
        source_refs=source_refs,
    )
    return _assistant_draft_response(
        user.user_id,
        project_id,
        question.strip(),
        mode,
        conversation_id,
        answer,
        sources,
    )


@router.post("/approve", response_model=ConversationDetailResponse)
def approve_draft(
    project_id: uuid.UUID,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    draft = _load_approval_draft(payload.approval_token, user.user_id, project_id)
    require_project_access(db, project_id, user.user_id)
    approval_id = hashlib.sha256(payload.approval_token.encode("utf-8")).hexdigest()

    existing_response = _approved_response(
        db, literature_db, approval_id, user.user_id, project_id
    )
    if existing_response is not None:
        return existing_response

    conversation_id = (
        uuid.UUID(draft["conversation_id"]) if draft.get("conversation_id") else uuid.uuid4()
    )
    if draft.get("conversation_id"):
        conversation = _conversation_for_user(db, conversation_id, user.user_id, project_id)
    else:
        title = draft["question"].strip().replace("\n", " ")[:120]
        conversation = Conversation(
            conversation_id=conversation_id,
            user_id=user.user_id,
            project_id=project_id,
            title=title or "Research conversation",
        )
        db.add(conversation)

    source_pairs: list[tuple[str, uuid.UUID]] = []
    for source in draft.get("sources", []):
        source_id = uuid.UUID(source["id"])
        if source["kind"] == "document":
            exists = db.scalar(
                select(DocumentChunk.chunk_id)
                .join(Document, Document.document_id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.chunk_id == source_id,
                    Document.project_id == project_id,
                )
            )
            if exists is None:
                raise HTTPException(
                    status_code=409, detail="A cited document was removed; generate a new answer."
                )
            source_pairs.append(("document", source_id))
        elif source["kind"] == "paper":
            if literature_db.get(Paper, source_id) is None:
                raise HTTPException(
                    status_code=409, detail="A cited paper is no longer available; generate a new answer."
                )
            source_pairs.append(("paper", source_id))
        else:
            raise HTTPException(status_code=400, detail="The review contains an invalid source.")

    message_time = datetime.now(timezone.utc)
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=draft["question"],
        reviewed=True,
        created_at=message_time,
    )
    assistant_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=draft["answer"],
        reviewed=True,
        approval_id=approval_id,
        created_at=message_time + timedelta(microseconds=1),
    )
    db.add_all([user_message, assistant_message])
    db.flush()
    for source_order, (kind, source_id) in enumerate(source_pairs):
        if kind == "document":
            db.add(
                MessageChunkSource(
                    message_id=assistant_message.message_id,
                    chunk_id=source_id,
                    source_order=source_order,
                )
            )
        else:
            db.add(
                MessagePaperSource(
                    message_id=assistant_message.message_id,
                    paper_id=source_id,
                    source_order=source_order,
                )
            )
    record_activity(
        db,
        user.user_id,
        "assistant.draft_approved",
        {"mode": draft["mode"], "source_count": len(source_pairs)},
    )
    conversation.updated_at = datetime.now(timezone.utc)
    existing_response = _commit_approval(
        db, literature_db, approval_id, user.user_id, project_id
    )
    if existing_response is not None:
        return existing_response
    db.refresh(conversation)
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    return _conversation_detail(db, literature_db, conversation, messages)
