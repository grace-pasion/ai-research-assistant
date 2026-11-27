import socket
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentPaper,
    Paper,
    ProjectActivity,
    ProjectPaper,
    ResearchProject,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import papers as papers_router
from app.services import academic_search


@pytest.fixture
def paper_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        UserActivity,
        ProjectActivity,
        TeamWorkspace,
        ResearchProject,
        ProjectPaper,
        Document,
        DocumentPaper,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)
    with Session(research_engine) as research_db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        research_db.add(user)
        research_db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        research_db.add(project)
        research_db.flush()
        paper = Paper(
            external_paper_id="W123",
            api_provider="openalex",
            title="An open study",
            doi="10.1000/example",
        )
        literature_db.add(paper)
        literature_db.flush()
        research_db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
        research_db.commit()
        literature_db.commit()
        yield research_db, literature_db, user, project, paper
    research_engine.dispose()
    literature_engine.dispose()


def test_import_open_access_paper_creates_queryable_project_document(
    paper_databases, monkeypatch
):
    db, literature_db, user, project, paper = paper_databases
    monkeypatch.setattr(papers_router, "open_access_pdf_url", lambda _paper: "https://repo.test/a.pdf")
    monkeypatch.setattr(
        papers_router,
        "download_open_access_pdf",
        lambda _url, _limit: b"%PDF-1.4 mock-pdf",
    )
    monkeypatch.setattr(papers_router, "store_document", lambda *_args: "stored-paper.pdf")
    monkeypatch.setattr(
        papers_router,
        "get_settings",
        lambda: SimpleNamespace(max_upload_mb=25),
    )
    background_tasks = BackgroundTasks()

    document = papers_router.import_open_access_full_text(
        project.project_id,
        paper.paper_id,
        background_tasks,
        db,
        literature_db,
        user,
    )

    assert document.processing_status == "processing"
    assert document.file_type == "pdf"
    relation = db.get(DocumentPaper, (document.document_id, paper.paper_id))
    assert relation is not None
    assert relation.relationship_type == "full_text"
    assert len(background_tasks.tasks) == 1
    assert db.scalar(select(UserActivity).where(UserActivity.action == "paper.full_text.imported"))

    duplicate = papers_router.import_open_access_full_text(
        project.project_id,
        paper.paper_id,
        BackgroundTasks(),
        db,
        literature_db,
        user,
    )
    assert duplicate.document_id == document.document_id


def test_import_paper_without_open_access_pdf_suggests_upload_fallback(
    paper_databases, monkeypatch
):
    db, literature_db, user, project, paper = paper_databases
    monkeypatch.setattr(papers_router, "open_access_pdf_url", lambda _paper: None)

    with pytest.raises(HTTPException) as error:
        papers_router.import_open_access_full_text(
            project.project_id,
            paper.paper_id,
            BackgroundTasks(),
            db,
            literature_db,
            user,
        )

    assert error.value.status_code == 404
    assert "upload a copy" in error.value.detail


def test_openalex_pdf_lookup_requires_open_access_location(monkeypatch):
    request = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "open_access": {"is_oa": True},
                "primary_location": {
                    "is_oa": True,
                    "pdf_url": "https://repository.example/paper.pdf",
                },
                "locations": [],
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, *, params):
            request["url"] = url
            request["params"] = params
            return FakeResponse()

    monkeypatch.setattr(academic_search.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        academic_search,
        "get_settings",
        lambda: SimpleNamespace(openalex_api_key=None, openalex_email=None),
    )

    paper = SimpleNamespace(api_provider="openalex", external_paper_id="W123", doi=None)
    assert academic_search.open_access_pdf_url(paper) == "https://repository.example/paper.pdf"
    assert request["url"].endswith("/W123")


def test_pdf_download_enforces_size_limit_and_public_host(monkeypatch):
    monkeypatch.setattr(
        academic_search.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    class FakeResponse:
        is_redirect = False
        headers = {"content-length": "17"}

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"%PDF-1.4 mock-pdf"

    class FakeStream:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *_args):
            pass

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def stream(self, _method, _url):
            return FakeStream()

    monkeypatch.setattr(academic_search.httpx, "Client", FakeClient)
    assert academic_search.download_open_access_pdf(
        "https://repository.example/paper.pdf", 32
    ) == b"%PDF-1.4 mock-pdf"

    with pytest.raises(academic_search.OpenAccessPDFTooLarge):
        academic_search.download_open_access_pdf("https://repository.example/paper.pdf", 8)

    monkeypatch.setattr(
        academic_search.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(ValueError, match="non-public"):
        academic_search.download_open_access_pdf("https://repository.example/paper.pdf", 32)
