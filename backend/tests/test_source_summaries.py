import hashlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Document,
    DocumentPaper,
    Paper,
    ProjectInvitation,
    ProjectPaper,
    ProjectSourceSummary,
    ResearchProject,
    User,
)
from app.routers import source_summaries
from app.schemas import ProjectSourceSummaryRequest
from app.security import get_current_user
from app.services import source_summarization


@pytest.fixture
def summary_context(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        ResearchProject,
        ProjectInvitation,
        Document,
        DocumentPaper,
        ProjectPaper,
        ProjectSourceSummary,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(email="owner@example.com", name="Owner", password_hash="hashed")
        reader = User(email="reader@example.com", name="Reader", password_hash="hashed")
        db.add_all([owner, reader])
        db.flush()
        project = ResearchProject(
            user_id=owner.user_id,
            project_name="Field notes",
            description="",
        )
        db.add(project)
        db.flush()
        document = Document(
            project_id=project.project_id,
            filename="field-notes.pdf",
            file_type="pdf",
            storage_path="field-notes.pdf",
            file_size=20,
            extracted_text="The document reports a clear result.",
            processing_status="ready",
        )
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="A useful paper",
            abstract="<p>The abstract reports a useful result.</p>",
        )
        db.add(document)
        literature_db.add(paper)
        db.flush()
        literature_db.flush()
        db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
        db.add(
            ProjectInvitation(
                project_id=project.project_id,
                inviter_id=owner.user_id,
                invitee_id=reader.user_id,
                status="accepted",
                role="read",
            )
        )
        db.add(
            DocumentPaper(
                document_id=document.document_id,
                paper_id=paper.paper_id,
                relationship_type="full_text",
            )
        )
        db.commit()
        yield db, literature_db, owner, project, document, paper


def _summarize(db, literature_db, user, project, source_type, source_id):
    return source_summaries.summarize_project_source(
        project.project_id,
        ProjectSourceSummaryRequest(source_type=source_type, source_id=source_id),
        db,
        literature_db,
        user,
    )


def test_document_summary_is_persisted_and_reused(summary_context, monkeypatch):
    db, literature_db, owner, project, document, _ = summary_context
    generated = []

    def generate(title, text):
        generated.append((title, text))
        return "A saved summary."

    monkeypatch.setattr(source_summaries, "generate_source_summary", generate)

    first = _summarize(db, literature_db, owner, project, "document", document.document_id)
    second = _summarize(db, literature_db, owner, project, "document", document.document_id)

    assert first.summary == "A saved summary."
    assert first.cached is False
    assert second.cached is True
    assert len(generated) == 1
    assert generated[0] == ("field-notes.pdf", "The document reports a clear result.")
    assert db.query(ProjectSourceSummary).count() == 1


def test_changed_document_text_generates_a_new_saved_summary(summary_context, monkeypatch):
    db, literature_db, owner, project, document, _ = summary_context
    generated = []
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: generated.append(text) or f"Summary {len(generated)}",
    )

    first = _summarize(db, literature_db, owner, project, "document", document.document_id)
    document.extracted_text = "The updated document reports a different result."
    db.commit()
    second = _summarize(db, literature_db, owner, project, "document", document.document_id)

    assert first.summary == "Summary 1"
    assert second.summary == "Summary 2"
    assert second.cached is False
    assert len(generated) == 2
    assert db.query(ProjectSourceSummary).count() == 1


def test_summary_policy_change_regenerates_existing_cache(summary_context, monkeypatch):
    db, literature_db, owner, project, document, _ = summary_context
    old_hash = hashlib.sha256(
        f"document\0{document.filename}\0{document.extracted_text}".encode("utf-8")
    ).hexdigest()
    db.add(
        ProjectSourceSummary(
            project_id=project.project_id,
            source_type="document",
            source_id=document.document_id,
            source_hash=old_hash,
            summary_text="A previously cached summary.",
        )
    )
    db.commit()
    generated = []
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: generated.append((title, text)) or "A refreshed summary.",
    )

    result = _summarize(db, literature_db, owner, project, "document", document.document_id)

    assert result.summary == "A refreshed summary."
    assert result.cached is False
    assert generated == [(document.filename, document.extracted_text)]


def test_saved_paper_summary_prefers_imported_full_text(summary_context, monkeypatch):
    db, literature_db, owner, project, document, paper = summary_context
    captured = []
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: captured.append((title, text)) or "A full-text summary.",
    )

    result = _summarize(db, literature_db, owner, project, "paper", paper.paper_id)

    assert result.summary == "A full-text summary."
    assert captured == [("A useful paper", "The document reports a clear result.")]


def test_saved_paper_summary_falls_back_to_abstract(summary_context, monkeypatch):
    db, literature_db, owner, project, _, _ = summary_context
    paper = Paper(
        external_paper_id="paper-2",
        api_provider="openalex",
        title="Abstract-only paper",
        abstract="<p>Abstract &amp; findings.</p>",
    )
    literature_db.add(paper)
    literature_db.flush()
    db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
    db.commit()
    captured = []
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: captured.append((title, text)) or "An abstract summary.",
    )

    result = _summarize(db, literature_db, owner, project, "paper", paper.paper_id)

    assert result.summary == "An abstract summary."
    assert captured == [("Abstract-only paper", "Abstract & findings.")]


def test_unready_document_returns_conflict_without_generation(summary_context, monkeypatch):
    db, literature_db, owner, project, document, _ = summary_context
    document.processing_status = "processing"
    db.commit()
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: pytest.fail("A document still processing must not be summarized."),
    )

    with pytest.raises(HTTPException) as error:
        _summarize(db, literature_db, owner, project, "document", document.document_id)

    assert error.value.status_code == 409


def test_cannot_summarize_a_document_from_another_project(summary_context, monkeypatch):
    db, literature_db, owner, project, _, _ = summary_context
    other_project = ResearchProject(
        user_id=owner.user_id,
        project_name="Other project",
        description="",
    )
    db.add(other_project)
    db.flush()
    other_document = Document(
        project_id=other_project.project_id,
        filename="private.pdf",
        file_type="pdf",
        storage_path="private.pdf",
        file_size=10,
        extracted_text="Private text.",
        processing_status="ready",
    )
    db.add(other_document)
    db.commit()
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: pytest.fail("A source outside the requested project must not be summarized."),
    )

    with pytest.raises(HTTPException) as error:
        _summarize(db, literature_db, owner, project, "document", other_document.document_id)

    assert error.value.status_code == 404


def test_project_reader_can_generate_and_reuse_summary(summary_context, monkeypatch):
    db, literature_db, _, project, document, _ = summary_context
    reader = db.query(User).filter_by(email="reader@example.com").one()
    generated = []
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: generated.append(text) or "A shared summary.",
    )

    first = _summarize(db, literature_db, reader, project, "document", document.document_id)
    second = _summarize(db, literature_db, reader, project, "document", document.document_id)

    assert first.summary == "A shared summary."
    assert first.cached is False
    assert second.cached is True
    assert len(generated) == 1


def test_user_without_project_access_cannot_generate_summary(summary_context, monkeypatch):
    db, literature_db, _, project, document, _ = summary_context
    outsider = User(email="outsider@example.com", name="Outsider", password_hash="hashed")
    db.add(outsider)
    db.commit()
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: pytest.fail("A user without project access must not get a summary."),
    )

    with pytest.raises(HTTPException) as error:
        _summarize(db, literature_db, outsider, project, "document", document.document_id)

    assert error.value.status_code == 404


def test_unsaved_paper_cannot_be_summarized(summary_context, monkeypatch):
    db, literature_db, owner, project, _, _ = summary_context
    paper = Paper(
        external_paper_id=str(uuid.uuid4()),
        api_provider="openalex",
        title="Not saved",
        abstract="An abstract.",
    )
    literature_db.add(paper)
    literature_db.commit()
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: pytest.fail("An unsaved paper must not be summarized."),
    )

    with pytest.raises(HTTPException) as error:
        _summarize(db, literature_db, owner, project, "paper", paper.paper_id)

    assert error.value.status_code == 404


def test_authenticated_summary_api_returns_saved_cache_result(summary_context, monkeypatch):
    db, literature_db, owner, project, document, _ = summary_context
    monkeypatch.setattr(
        source_summaries,
        "generate_source_summary",
        lambda title, text: "A saved summary.",
    )
    app = FastAPI()
    app.include_router(source_summaries.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_literature_db] = lambda: literature_db
    app.dependency_overrides[get_current_user] = lambda: owner

    with TestClient(app) as client:
        response = client.post(
            f"/api/projects/{project.project_id}/source-summaries",
            json={"source_type": "document", "source_id": str(document.document_id)},
        )

    assert response.status_code == 200
    assert response.json()["summary"] == "A saved summary."
    assert response.json()["cached"] is False


def test_summary_service_uses_configured_ai_and_treats_source_as_untrusted(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A careful summary."))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(source_summarization, "OpenAI", lambda api_key: client)
    monkeypatch.setattr(
        source_summarization,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=SecretStr("test-key"), openai_model="test-model"),
    )

    result = source_summarization.generate_source_summary("Study title", "Study findings.")

    assert result == "A careful summary."
    assert len(calls) == 1
    assert calls[0]["model"] == "test-model"
    assert calls[0]["messages"][0]["role"] == "system"
    assert "untrusted data" in calls[0]["messages"][0]["content"]
    assert "Study findings." in calls[0]["messages"][1]["content"]
    assert "do not strengthen comparisons" in calls[0]["messages"][0]["content"]
    assert "Preserve the source's distinctions and qualifiers" in calls[0]["messages"][1]["content"]
    assert "omit the detail rather than infer it" in calls[0]["messages"][1]["content"]


def test_summary_service_synthesizes_long_sources_in_chunks(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"Part {len(calls)}"))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(source_summarization, "OpenAI", lambda api_key: client)
    monkeypatch.setattr(
        source_summarization,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=SecretStr("test-key"), openai_model="test-model"),
    )

    result = source_summarization.generate_source_summary(
        "Long study",
        "Evidence " * (source_summarization.SUMMARY_CHUNK_CHARACTERS // 8 + 1),
    )

    assert result == f"Part {len(calls)}"
    assert len(calls) == 3
    assert "Part 1" in calls[-1]["messages"][1]["content"]
    assert "Part 2" in calls[-1]["messages"][1]["content"]


def test_summary_service_reports_missing_key_and_oversized_source(monkeypatch):
    monkeypatch.setattr(
        source_summarization,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_model="test-model"),
    )

    with pytest.raises(HTTPException) as missing_key:
        source_summarization.generate_source_summary("Study", "Readable text.")
    assert missing_key.value.status_code == 503

    with pytest.raises(HTTPException) as oversized:
        source_summarization.generate_source_summary(
            "Study",
            "x" * (source_summarization.MAX_SOURCE_CHARACTERS + 1),
        )
    assert oversized.value.status_code == 413
