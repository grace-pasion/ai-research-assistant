import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.routers.documents as documents_router
import app.routers.papers as papers_router
from app.database import ensure_library_metadata_columns, get_db
from app.models import Document, ProjectPaper
from app.security import get_current_user
from app.schemas import DocumentResponse, LibraryMetadataUpdate


@pytest.fixture
def library_items(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'library.sqlite'}")
    Document.__table__.create(engine)
    ProjectPaper.__table__.create(engine)
    with Session(engine) as db:
        document = Document(
            project_id=uuid.uuid4(),
            filename="study.pdf",
            file_type="pdf",
            storage_path="test://study.pdf",
            file_size=100,
            processing_status="ready",
        )
        relation = ProjectPaper(project_id=uuid.uuid4(), paper_id=uuid.uuid4())
        db.add_all([document, relation])
        db.commit()
        yield db, document, relation
    engine.dispose()


def test_document_tags_and_metadata_are_saved_and_returned(library_items, monkeypatch):
    db, document, _relation = library_items
    user = type("UserStub", (), {"user_id": uuid.uuid4()})()
    access_checks = []
    monkeypatch.setattr(
        documents_router,
        "require_project_access",
        lambda *args: access_checks.append(args[2:]),
    )
    monkeypatch.setattr(documents_router, "record_activity", lambda *_args, **_kwargs: None)

    updated = documents_router.update_document_metadata(
        document.document_id,
        LibraryMetadataUpdate(
            tags=["  Methods ", "methods", " Priority"],
            metadata={" Study design ": " Randomized trial "},
        ),
        db,
        user,
    )
    response = DocumentResponse.model_validate(updated)

    assert access_checks == [(user.user_id, "edit")]
    assert response.tags == ["Methods", "Priority"]
    assert response.metadata == {"Study design": "Randomized trial"}
    assert "metadata" in response.model_dump()


def test_paper_tags_and_metadata_are_project_scoped(library_items, monkeypatch):
    db, _document, relation = library_items
    user = type("UserStub", (), {"user_id": uuid.uuid4()})()
    access_checks = []
    monkeypatch.setattr(
        papers_router,
        "require_project_access",
        lambda *args: access_checks.append(args[2:]),
    )
    monkeypatch.setattr(papers_router, "record_activity", lambda *_args, **_kwargs: None)

    response = papers_router.update_paper_metadata(
        relation.project_id,
        relation.paper_id,
        LibraryMetadataUpdate(tags=["Evidence"], metadata={"cohort": "adults"}),
        db,
        user,
    )

    assert access_checks == [(user.user_id, "edit")]
    assert response.tags == ["Evidence"]
    assert response.metadata == {"cohort": "adults"}
    assert db.get(ProjectPaper, (relation.project_id, relation.paper_id)).custom_metadata == {
        "cohort": "adults"
    }


def test_metadata_updates_reject_missing_library_items(library_items, monkeypatch):
    db, _document, relation = library_items
    user = type("UserStub", (), {"user_id": uuid.uuid4()})()
    monkeypatch.setattr(documents_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(papers_router, "require_project_access", lambda *_args: None)
    payload = LibraryMetadataUpdate(tags=[], metadata={})

    with pytest.raises(HTTPException) as missing_document:
        documents_router.update_document_metadata(uuid.uuid4(), payload, db, user)
    with pytest.raises(HTTPException) as missing_paper:
        papers_router.update_paper_metadata(
            relation.project_id, uuid.uuid4(), payload, db, user
        )

    assert missing_document.value.status_code == 404
    assert missing_paper.value.status_code == 404


def test_metadata_patch_routes_return_public_metadata_fields(library_items, monkeypatch):
    db, document, relation = library_items
    user = type("UserStub", (), {"user_id": uuid.uuid4()})()
    monkeypatch.setattr(documents_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(papers_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(documents_router, "record_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(papers_router, "record_activity", lambda *_args, **_kwargs: None)
    app = FastAPI()
    app.include_router(documents_router.router)
    app.include_router(papers_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    document_response = client.patch(
        f"/api/documents/{document.document_id}/metadata",
        json={"tags": ["protocol"], "metadata": {"source": "manual"}},
    )
    paper_response = client.patch(
        f"/api/projects/{relation.project_id}/papers/{relation.paper_id}/metadata",
        json={"tags": ["priority"], "metadata": {"stage": "screening"}},
    )

    assert document_response.status_code == 200
    assert document_response.json()["metadata"] == {"source": "manual"}
    assert document_response.json()["tags"] == ["protocol"]
    assert "custom_metadata" not in document_response.json()
    assert paper_response.status_code == 200
    assert paper_response.json() == {
        "tags": ["priority"],
        "metadata": {"stage": "screening"},
    }


def test_metadata_schema_normalizes_and_rejects_invalid_values():
    assert LibraryMetadataUpdate(
        tags=["  methods  ", "Methods"],
        metadata={" design ": "  trial "},
    ).model_dump() == {"tags": ["methods"], "metadata": {"design": "trial"}}

    with pytest.raises(ValidationError):
        LibraryMetadataUpdate(tags=[" "], metadata={})
    with pytest.raises(ValidationError):
        LibraryMetadataUpdate(tags=[], metadata={"a": "x", " A ": "y"})
    with pytest.raises(ValidationError):
        LibraryMetadataUpdate(tags=["x" * 65], metadata={})
    with pytest.raises(ValidationError):
        LibraryMetadataUpdate(tags=[], metadata={"study": "x" * 501})


def test_existing_document_and_project_paper_tables_receive_empty_metadata_defaults(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE documents (document_id CHAR(32) PRIMARY KEY, filename TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE project_papers (project_id CHAR(32), paper_id CHAR(32), "
                "PRIMARY KEY (project_id, paper_id))"
            )
        )
        connection.execute(
            text("INSERT INTO documents (document_id, filename) VALUES ('doc', 'legacy.pdf')")
        )
        connection.execute(
            text(
                "INSERT INTO project_papers (project_id, paper_id) "
                "VALUES ('project', 'paper')"
            )
        )

    ensure_library_metadata_columns(engine)

    with engine.connect() as connection:
        document = connection.execute(
            text("SELECT tags, metadata FROM documents WHERE document_id = 'doc'")
        ).one()
        paper = connection.execute(
            text(
                "SELECT tags, metadata FROM project_papers "
                "WHERE project_id = 'project' AND paper_id = 'paper'"
            )
        ).one()
    assert document == ("[]", "{}")
    assert paper == ("[]", "{}")
    engine.dispose()
