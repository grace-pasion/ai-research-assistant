import io
import json
import uuid
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Annotation,
    Author,
    Conversation,
    Document,
    LatexWorkspace,
    Message,
    Paper,
    PaperAuthor,
    ProjectInvitation,
    ProjectPaper,
    PythonWorkspace,
    PythonWorkspaceArtifact,
    ResearchProject,
    SystematicReviewWorkspace,
    User,
)
from app.routers import project_exports
from app.schemas import ConversationDetailResponse, ConversationMessageResponse, SourceResponse
from app.security import get_current_user


@pytest.fixture
def project_export_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        ResearchProject,
        ProjectInvitation,
        Document,
        ProjectPaper,
        Annotation,
        LatexWorkspace,
        PythonWorkspace,
        PythonWorkspaceArtifact,
        SystematicReviewWorkspace,
        Conversation,
        Message,
    ):
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(email="owner@example.com", name="Owner", password_hash="hashed")
        reader = User(email="reader@example.com", name="Reader", password_hash="hashed")
        db.add_all([owner, reader])
        db.flush()
        project = ResearchProject(
            user_id=owner.user_id,
            project_name="Field notes",
            description="A project description",
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectInvitation(
                project_id=project.project_id,
                inviter_id=owner.user_id,
                invitee_id=reader.user_id,
                status="accepted",
                role="read",
            )
        )

        document = Document(
            project_id=project.project_id,
            filename="../private source.pdf",
            file_type="pdf",
            storage_path="private/source.pdf",
            file_size=19,
            extracted_text="Extracted text must not be in the default export.",
            processing_status="ready",
        )
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="A portable study",
            abstract="Study abstract",
            publication_year=2024,
            doi="10.1234/portable",
            paper_url="https://example.test/paper",
            venue="Journal of Portability",
        )
        db.add(document)
        literature_db.add(paper)
        db.flush()
        literature_db.flush()
        author = Author(
            author_name="Ada Researcher",
            external_author_id="author-1",
            api_provider="openalex",
        )
        literature_db.add(author)
        literature_db.flush()
        literature_db.add(PaperAuthor(paper_id=paper.paper_id, author_id=author.author_id, author_order=0))
        db.add(
            ProjectPaper(
                project_id=project.project_id,
                paper_id=paper.paper_id,
                screening_status="include",
                screening_note="Meets criteria",
            )
        )
        db.add(
            Annotation(
                project_id=project.project_id,
                document_id=document.document_id,
                created_by=reader.user_id,
                quote="important evidence",
                note="Keep this passage.",
            )
        )
        db.add(
            LatexWorkspace(
                project_id=project.project_id,
                main_tex=r"\section{Findings}",
                references_bib="@article{portable2024, title={A portable study}}",
            )
        )
        db.add(
            SystematicReviewWorkspace(
                project_id=project.project_id,
                review_question="What can be preserved?",
                protocol="Include portable studies.",
            )
        )
        db.add(
            PythonWorkspace(
                project_id=project.project_id,
                code="print('portable')",
                files=[
                    {"filename": "main.py", "code": "print('portable')"},
                    {"filename": "analysis.py", "code": "from helpers import summarize"},
                    {"filename": "helpers.py", "code": "def summarize(): return 1"},
                ],
            )
        )
        db.add(
            PythonWorkspaceArtifact(
                project_id=project.project_id,
                filename="figure.png",
                content_type="image/png",
                content=b"\x89PNG\r\n\x1a\nfigure",
                byte_size=14,
            )
        )
        owner_conversation = Conversation(
            user_id=owner.user_id,
            project_id=project.project_id,
            title="Owner's private conversation",
        )
        reader_conversation = Conversation(
            user_id=reader.user_id,
            project_id=project.project_id,
            title="Reader's private conversation",
        )
        db.add_all([owner_conversation, reader_conversation])
        db.flush()
        db.add_all(
            [
                Message(
                    conversation_id=owner_conversation.conversation_id,
                    role="user",
                    content="Only the owner should see this.",
                ),
                Message(
                    conversation_id=reader_conversation.conversation_id,
                    role="user",
                    content="Only the reader should see this.",
                ),
            ]
        )
        db.commit()
        yield (
            db,
            literature_db,
            owner,
            reader,
            project,
            document,
            paper,
            owner_conversation,
            reader_conversation,
        )

    research_engine.dispose()
    literature_engine.dispose()


def _client(db, literature_db, user):
    app = FastAPI()
    app.include_router(project_exports.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_literature_db] = lambda: literature_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _read_archive(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


def test_project_export_contains_shared_content_but_omits_optional_private_data_by_default(
    project_export_databases, monkeypatch
):
    (
        db,
        literature_db,
        _owner,
        reader,
        project,
        document,
        _paper,
        _owner_conversation,
        _reader_conversation,
    ) = project_export_databases

    def unexpected_document_read(_storage_path):
        pytest.fail("Original documents must not be read unless explicitly selected.")

    monkeypatch.setattr(project_exports, "read_document", unexpected_document_read)
    with _client(db, literature_db, reader) as client:
        response = client.get(f"/api/projects/{project.project_id}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="project-backup.zip"'
    with _read_archive(response.content) as archive:
        names = set(archive.namelist())
        assert {
            "README.txt",
            "manifest.json",
            "project.json",
            "documents/index.json",
            "references/references.json",
            "references/references.ris",
            "references/references.bib",
            "notes/annotations.json",
            "writing/main.tex",
            "writing/references.bib",
            "writing/python/main.py",
            "writing/python/analysis.py",
            "writing/python/helpers.py",
            "writing/python-output/figure.png",
            "review/systematic_review.json",
        }.issubset(names)
        assert not any(name.startswith("original_documents/") for name in names)
        assert not any(name.startswith("conversations/") for name in names)

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["options"] == {
            "include_original_documents": False,
            "include_conversations": False,
        }
        assert manifest["conversation_scope"] == "not_included"
        project_data = json.loads(archive.read("project.json"))
        assert project_data["project_name"] == "Field notes"
        documents = json.loads(archive.read("documents/index.json"))
        assert documents[0]["document_id"] == str(document.document_id)
        assert documents[0]["original_included"] is False
        assert "storage_path" not in documents[0]
        assert "extracted_text" not in documents[0]
        references = json.loads(archive.read("references/references.json"))
        assert references[0]["title"] == "A portable study"
        assert references[0]["screening_status"] == "include"
        assert references[0]["authors"][0]["author_name"] == "Ada Researcher"
        notes = json.loads(archive.read("notes/annotations.json"))
        assert notes[0]["note"] == "Keep this passage."
        assert archive.read("writing/main.tex").decode("utf-8") == r"\section{Findings}"
        assert "portable2024" in archive.read("writing/references.bib").decode("utf-8")
        assert archive.read("writing/python/main.py").decode("utf-8") == "print('portable')"
        assert archive.read("writing/python/analysis.py").decode("utf-8") == "from helpers import summarize"
        assert archive.read("writing/python-output/figure.png") == b"\x89PNG\r\n\x1a\nfigure"
        assert manifest["python_workspace_saved"] is True
        assert manifest["python_artifact_count"] == 1


def test_optional_export_includes_original_bytes_and_only_requesters_conversations(
    project_export_databases, monkeypatch
):
    (
        db,
        literature_db,
        _owner,
        reader,
        project,
        document,
        _paper,
        owner_conversation,
        reader_conversation,
    ) = project_export_databases
    original_bytes = b"%PDF-1.7 original source"
    monkeypatch.setattr(project_exports, "read_document", lambda _path: original_bytes)

    with _client(db, literature_db, reader) as client:
        response = client.get(
            f"/api/projects/{project.project_id}/export",
            params={"include_original_documents": True, "include_conversations": True},
        )

    assert response.status_code == 200
    with _read_archive(response.content) as archive:
        names = set(archive.namelist())
        original_name = f"original_documents/{document.document_id}/private source.pdf"
        reader_chat_name = f"conversations/{reader_conversation.conversation_id}.json"
        owner_chat_name = f"conversations/{owner_conversation.conversation_id}.json"
        assert original_name in names
        assert archive.read(original_name) == original_bytes
        assert reader_chat_name in names
        assert owner_chat_name not in names
        assert all(
            part not in {".", ".."}
            for name in names
            for part in name.split("/")
        )
        reader_chat = json.loads(archive.read(reader_chat_name))
        assert reader_chat["title"] == "Reader's private conversation"
        assert reader_chat["messages"][0]["content"] == "Only the reader should see this."
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["options"] == {
            "include_original_documents": True,
            "include_conversations": True,
        }
        assert manifest["conversation_scope"] == "requesting_user_only"


def test_conversation_sources_are_limited_to_the_exported_project(
    project_export_databases, monkeypatch
):
    (
        db,
        literature_db,
        _owner,
        reader,
        project,
        document,
        paper,
        _owner_conversation,
        reader_conversation,
    ) = project_export_databases
    message = db.scalar(
        select(Message).where(
            Message.conversation_id == reader_conversation.conversation_id
        )
    )
    assert message is not None
    foreign_document_id = uuid.uuid4()
    foreign_paper_id = uuid.uuid4()

    def fake_conversation_detail(_db, _literature_db, conversation, messages):
        return ConversationDetailResponse(
            conversation_id=conversation.conversation_id,
            project_id=conversation.project_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[
                ConversationMessageResponse(
                    message_id=messages[0].message_id,
                    conversation_id=conversation.conversation_id,
                    role="assistant",
                    content="Answer",
                    created_at=messages[0].created_at,
                    reviewed=True,
                    sources=[
                        SourceResponse(
                            kind="document",
                            source_id=document.document_id,
                            document_id=document.document_id,
                            title=document.filename,
                            excerpt="Project source",
                        ),
                        SourceResponse(
                            kind="document",
                            source_id=foreign_document_id,
                            document_id=foreign_document_id,
                            title="Other project source",
                            excerpt="Private document text",
                        ),
                        SourceResponse(
                            kind="paper",
                            source_id=paper.paper_id,
                            paper_id=paper.paper_id,
                            title=paper.title,
                            excerpt="Project paper",
                        ),
                        SourceResponse(
                            kind="paper",
                            source_id=foreign_paper_id,
                            paper_id=foreign_paper_id,
                            title="Other project paper",
                            excerpt="Unrelated paper",
                        ),
                    ],
                )
            ],
        )

    monkeypatch.setattr(project_exports, "_conversation_detail", fake_conversation_detail)
    with _client(db, literature_db, reader) as client:
        response = client.get(
            f"/api/projects/{project.project_id}/export",
            params={"include_conversations": True},
        )

    assert response.status_code == 200
    with _read_archive(response.content) as archive:
        chat_path = f"conversations/{reader_conversation.conversation_id}.json"
        chat = json.loads(archive.read(chat_path))
        sources = chat["messages"][0]["sources"]
        assert [source["title"] for source in sources] == [
            document.filename,
            paper.title,
        ]


def test_project_export_rejects_non_collaborators(project_export_databases):
    db, literature_db, _owner, _reader, project, *_rest = project_export_databases
    outsider = User(
        user_id=uuid.uuid4(),
        email="outsider@example.com",
        name="Outsider",
        password_hash="hashed",
    )
    with _client(db, literature_db, outsider) as client:
        response = client.get(f"/api/projects/{project.project_id}/export")
    assert response.status_code == 404


def test_project_export_reports_original_storage_failure(project_export_databases, monkeypatch):
    db, literature_db, owner, _reader, project, *_rest = project_export_databases

    def fail_read(_storage_path):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(project_exports, "read_document", fail_read)
    with _client(db, literature_db, owner) as client:
        response = client.get(
            f"/api/projects/{project.project_id}/export",
            params={"include_original_documents": True},
        )
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Original project documents could not be read; the export was not created."
    )


def test_empty_project_still_has_a_complete_export_bundle(project_export_databases):
    db, literature_db, owner, _reader, _project, *_rest = project_export_databases
    empty_project = ResearchProject(
        user_id=owner.user_id,
        project_name="Empty project",
        description="",
    )
    db.add(empty_project)
    db.commit()

    with _client(db, literature_db, owner) as client:
        response = client.get(f"/api/projects/{empty_project.project_id}/export")

    assert response.status_code == 200
    with _read_archive(response.content) as archive:
        assert json.loads(archive.read("references/references.json")) == []
        assert archive.read("references/references.ris") == b""
        assert archive.read("references/references.bib") == b""
        review = json.loads(archive.read("review/systematic_review.json"))
        assert review == {"review_question": "", "protocol": "", "updated_at": None}
        assert json.loads(archive.read("documents/index.json")) == []
