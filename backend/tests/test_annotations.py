import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Annotation, Document, Paper, ProjectPaper, ResearchProject, User
from app.routers import annotations, documents
from app.schemas import AnnotationCreate, AnnotationUpdate


@pytest.fixture
def annotation_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (User, ResearchProject, Document, ProjectPaper, Annotation):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)
    with Session(research_engine) as research_db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        research_db.add(user)
        research_db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        research_db.add(project)
        research_db.flush()
        document = Document(
            project_id=project.project_id,
            filename="study.txt",
            file_type="txt",
            storage_path="study.txt",
            file_size=20,
            extracted_text="Evidence from the uploaded study.",
            processing_status="ready",
        )
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="A saved study",
            abstract="<p>Evidence from a <b>published</b> study.</p>",
        )
        research_db.add(document)
        literature_db.add(paper)
        research_db.flush()
        literature_db.flush()
        research_db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
        research_db.commit()
        literature_db.commit()
        yield research_db, literature_db, user, project, document, paper
    research_engine.dispose()
    literature_engine.dispose()


def test_document_annotations_persist_edit_and_delete(annotation_databases):
    db, _, user, project, document, _ = annotation_databases
    payload = AnnotationCreate(
        quote="uploaded study",
        note="Review this evidence.",
        start_offset=18,
        end_offset=32,
    )

    created = annotations.create_document_annotation(
        project.project_id, document.document_id, payload, db, user
    )
    loaded = annotations.list_document_annotations(project.project_id, document.document_id, db, user)
    assert len(loaded) == 1
    assert loaded[0].annotation_id == created.annotation_id
    assert loaded[0].quote == "uploaded study"
    assert loaded[0].start_offset == 18

    with Session(db.get_bind()) as fresh_db:
        logged_in_user = fresh_db.get(User, user.user_id)
        assert logged_in_user is not None
        persisted = annotations.list_document_annotations(
            project.project_id, document.document_id, fresh_db, logged_in_user
        )
        assert len(persisted) == 1
        assert persisted[0].note == "Review this evidence."

    updated = annotations.update_document_annotation(
        project.project_id,
        document.document_id,
        created.annotation_id,
        AnnotationUpdate(note="Updated note"),
        db,
        user,
    )
    assert updated.note == "Updated note"

    annotations.delete_document_annotation(
        project.project_id, document.document_id, created.annotation_id, db, user
    )
    assert annotations.list_document_annotations(project.project_id, document.document_id, db, user) == []


def test_document_annotation_rejects_stale_selection(annotation_databases):
    db, _, user, project, document, _ = annotation_databases
    with pytest.raises(HTTPException) as error:
        annotations.create_document_annotation(
            project.project_id,
            document.document_id,
            AnnotationCreate(quote="incorrect", note="", start_offset=0, end_offset=9),
            db,
            user,
        )
    assert error.value.status_code == 422
    assert db.scalar(select(Annotation)) is None


def test_paper_annotations_require_saved_paper_and_use_abstract_text(annotation_databases):
    db, literature_db, user, project, _, paper = annotation_databases
    created = annotations.create_paper_annotation(
        project.project_id,
        paper.paper_id,
        AnnotationCreate(quote="published", note="Important finding.", start_offset=16, end_offset=25),
        db,
        literature_db,
        user,
    )
    assert created.paper_id == paper.paper_id
    assert annotations.list_paper_annotations(
        project.project_id, paper.paper_id, db, literature_db, user
    ) == [created]

    with Session(db.get_bind()) as fresh_db:
        logged_in_user = fresh_db.get(User, user.user_id)
        assert logged_in_user is not None
        persisted = annotations.list_paper_annotations(
            project.project_id, paper.paper_id, fresh_db, literature_db, logged_in_user
        )
        assert len(persisted) == 1
        assert persisted[0].note == "Important finding."

    unsaved_paper_id = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        annotations.list_paper_annotations(
            project.project_id, unsaved_paper_id, db, literature_db, user
        )
    assert error.value.status_code == 404


def test_annotations_are_scoped_to_the_project_owner(annotation_databases):
    db, _, _, project, document, _ = annotation_databases
    other_user = User(
        user_id=uuid.uuid4(),
        email="other@example.com",
        name="Other",
        password_hash="hashed",
    )
    with pytest.raises(HTTPException) as error:
        annotations.list_document_annotations(project.project_id, document.document_id, db, other_user)
    assert error.value.status_code == 404


def test_document_reader_returns_extracted_text_only_to_the_owner(annotation_databases):
    db, _, user, _, document, _ = annotation_databases
    result = documents.read_document_text(document.document_id, db, user)
    assert result.filename == "study.txt"
    assert result.text == "Evidence from the uploaded study."

    other_user = User(
        user_id=uuid.uuid4(),
        email="reader2@example.com",
        name="Reader 2",
        password_hash="hashed",
    )
    with pytest.raises(HTTPException) as error:
        documents.read_document_text(document.document_id, db, other_user)
    assert error.value.status_code == 404
