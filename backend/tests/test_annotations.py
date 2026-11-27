import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.database import (
    ensure_annotation_synthesis_columns,
    get_db,
    get_literature_db,
)
from app.models import (
    Annotation,
    Document,
    Notification,
    Paper,
    ProjectActivity,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import annotations, documents
from app.schemas import AnnotationCreate, AnnotationUpdate
from app.security import get_current_user


@pytest.fixture
def annotation_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        UserActivity,
        ProjectActivity,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        Document,
        ProjectPaper,
        Annotation,
        Notification,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)
    with Session(research_engine) as research_db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", username="reader", name="Reader", password_hash="hashed")
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


def test_project_annotations_combine_and_search_saved_sources(annotation_databases):
    db, literature_db, user, project, document, paper = annotation_databases
    document_annotation = Annotation(
        project_id=project.project_id,
        document_id=document.document_id,
        quote="uploaded study",
        note="Check the methods.",
    )
    paper_annotation = Annotation(
        project_id=project.project_id,
        paper_id=paper.paper_id,
        quote="published study",
        note="Important finding.",
    )
    db.add_all([document_annotation, paper_annotation])
    db.commit()

    all_annotations = annotations.list_project_annotations(
        project.project_id, db=db, literature_db=literature_db, user=user
    )
    assert {item.source_type for item in all_annotations} == {"document", "paper"}
    assert {item.source_title for item in all_annotations} == {"study.txt", "A saved study"}

    matching = annotations.list_project_annotations(
        project.project_id, q="important finding", db=db, literature_db=literature_db, user=user
    )
    assert len(matching) == 1
    assert matching[0].annotation_id == paper_annotation.annotation_id

    db.delete(db.get(ProjectPaper, (project.project_id, paper.paper_id)))
    remaining = annotations.list_project_annotations(
        project.project_id, db=db, literature_db=literature_db, user=user
    )
    assert [item.annotation_id for item in remaining] == [document_annotation.annotation_id]


def test_project_annotations_require_project_access(annotation_databases):
    db, literature_db, _, project, _, _ = annotation_databases
    other_user = User(
        user_id=uuid.uuid4(),
        email="other@example.com",
        name="Other",
        password_hash="hashed",
    )
    with pytest.raises(HTTPException) as error:
        annotations.list_project_annotations(
            project.project_id, db=db, literature_db=literature_db, user=other_user
        )
    assert error.value.status_code == 404


def test_annotation_mentions_notify_only_new_project_collaborators(annotation_databases):
    db, _, owner, project, document, _ = annotation_databases
    collaborator = User(
        email="collaborator@example.com",
        username="collaborator",
        name="Project collaborator",
        password_hash="hashed",
    )
    db.add(collaborator)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=collaborator.user_id,
            role="comment",
            status="accepted",
        )
    )
    db.commit()

    created = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="Please review this, @collaborator."),
        db,
        owner,
    )
    notifications = db.scalars(select(Notification)).all()
    assert len(notifications) == 1
    assert notifications[0].recipient_id == collaborator.user_id
    assert notifications[0].kind == "annotation_mention"
    assert notifications[0].details["annotation_id"] == str(created.annotation_id)

    annotations.update_document_annotation(
        project.project_id,
        document.document_id,
        created.annotation_id,
        AnnotationUpdate(note="Thanks, @COLLABORATOR."),
        db,
        owner,
    )
    assert len(db.scalars(select(Notification)).all()) == 1

    annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="I will review this, @reader."),
        db,
        owner,
    )
    assert len(db.scalars(select(Notification)).all()) == 1

    invitation = db.scalar(
        select(ProjectInvitation).where(ProjectInvitation.invitee_id == collaborator.user_id)
    )
    assert invitation is not None
    invitation.status = "declined"
    db.commit()
    annotations.update_document_annotation(
        project.project_id,
        document.document_id,
        created.annotation_id,
        AnnotationUpdate(note="Revisiting this, @collaborator."),
        db,
        owner,
    )
    assert len(db.scalars(select(Notification)).all()) == 1


def test_annotation_mentions_reject_non_collaborators(annotation_databases):
    db, _, owner, project, document, _ = annotation_databases
    with pytest.raises(HTTPException) as error:
        annotations.create_document_annotation(
            project.project_id,
            document.document_id,
            AnnotationCreate(note="Please review this, @outsider."),
            db,
            owner,
        )
    assert error.value.status_code == 422
    assert db.scalar(select(Annotation)) is None


def test_annotation_updates_save_normalized_tags_pin_and_related_sources(annotation_databases):
    db, literature_db, user, project, document, paper = annotation_databases
    annotation = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="Synthesize this source."),
        db,
        user,
    )

    updated = annotations.update_document_annotation(
        project.project_id,
        document.document_id,
        annotation.annotation_id,
        AnnotationUpdate(
            tags=["  methods ", "Synthesis", "METHODS"],
            is_pinned=True,
            related_sources=[{"source_type": "paper", "source_id": str(paper.paper_id)}],
        ),
        db,
        user,
        literature_db=literature_db,
    )

    assert updated.tags == ["methods", "Synthesis"]
    assert updated.is_pinned is True
    assert updated.related_sources == [
        {"source_type": "paper", "source_id": str(paper.paper_id)}
    ]
    assert annotations.list_project_annotations(
        project.project_id, db=db, literature_db=literature_db, user=user
    )[0].tags == ["methods", "Synthesis"]
    assert [
        item.annotation_id
        for item in annotations.list_project_annotations(
            project.project_id,
            q="methods",
            db=db,
            literature_db=literature_db,
            user=user,
        )
    ] == [annotation.annotation_id]


def test_annotation_links_must_be_distinct_project_sources(annotation_databases):
    db, literature_db, user, project, document, paper = annotation_databases
    annotation = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="Synthesize this source."),
        db,
        user,
    )

    with pytest.raises(HTTPException) as same_source:
        annotations.update_document_annotation(
            project.project_id,
            document.document_id,
            annotation.annotation_id,
            AnnotationUpdate(
                related_sources=[
                    {"source_type": "document", "source_id": str(document.document_id)}
                ]
            ),
            db,
            user,
            literature_db=literature_db,
        )
    assert same_source.value.status_code == 422

    with pytest.raises(HTTPException) as unsaved_paper:
        annotations.update_document_annotation(
            project.project_id,
            document.document_id,
            annotation.annotation_id,
            AnnotationUpdate(
                related_sources=[
                    {"source_type": "paper", "source_id": str(uuid.uuid4())}
                ]
            ),
            db,
            user,
            literature_db=literature_db,
        )
    assert unsaved_paper.value.status_code == 404

    other_project = ResearchProject(user_id=user.user_id, project_name="Other project")
    db.add(other_project)
    db.flush()
    other_document = Document(
        project_id=other_project.project_id,
        filename="other.txt",
        file_type="txt",
        storage_path="other.txt",
        file_size=5,
        extracted_text="Other",
        processing_status="ready",
    )
    db.add(other_document)
    db.commit()
    with pytest.raises(HTTPException) as foreign_document:
        annotations.update_document_annotation(
            project.project_id,
            document.document_id,
            annotation.annotation_id,
            AnnotationUpdate(
                related_sources=[
                    {"source_type": "document", "source_id": str(other_document.document_id)}
                ]
            ),
            db,
            user,
            literature_db=literature_db,
        )
    assert foreign_document.value.status_code == 404

    with pytest.raises(HTTPException) as duplicate_source:
        annotations.update_document_annotation(
            project.project_id,
            document.document_id,
            annotation.annotation_id,
            AnnotationUpdate(
                related_sources=[
                    {"source_type": "paper", "source_id": str(paper.paper_id)},
                    {"source_type": "paper", "source_id": str(paper.paper_id)},
                ]
            ),
            db,
            user,
            literature_db=literature_db,
        )
    assert duplicate_source.value.status_code == 422


def test_annotation_metadata_patch_http_contract(annotation_databases):
    db, literature_db, user, project, document, paper = annotation_databases
    annotation = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="Synthesize this source."),
        db,
        user,
    )
    app = FastAPI()
    app.include_router(annotations.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_literature_db] = lambda: literature_db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as client:
        response = client.patch(
            f"/api/projects/{project.project_id}/documents/{document.document_id}/annotations/{annotation.annotation_id}",
            json={
                "tags": [" synthesis "],
                "is_pinned": True,
                "related_sources": [{"source_type": "paper", "source_id": str(paper.paper_id)}],
            },
        )

    assert response.status_code == 200
    assert response.json()["tags"] == ["synthesis"]
    assert response.json()["is_pinned"] is True
    assert response.json()["related_sources"] == [
        {"source_type": "paper", "source_id": str(paper.paper_id)}
    ]


def test_annotation_synthesis_migration_adds_defaults_and_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE annotations (annotation_id CHAR(32) PRIMARY KEY)")
        )
        connection.execute(
            text("INSERT INTO annotations (annotation_id) VALUES ('old-note')")
        )

    ensure_annotation_synthesis_columns(engine)
    ensure_annotation_synthesis_columns(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT tags, is_pinned, related_sources FROM annotations "
                "WHERE annotation_id = 'old-note'"
            )
        ).one()
    assert row.tags == "[]"
    assert row.is_pinned in (False, 0)
    assert row.related_sources == "[]"
    engine.dispose()


def test_comment_access_is_role_limited_and_authors_can_only_edit_their_own(annotation_databases):
    db, _, owner, project, document, _ = annotation_databases
    commenter = User(
        email="commenter@example.com",
        name="Commenter",
        password_hash="hashed",
    )
    reader = User(
        email="view-only@example.com",
        name="Reader",
        password_hash="hashed",
    )
    db.add_all((commenter, reader))
    db.flush()
    db.add_all(
        (
            ProjectInvitation(
                project_id=project.project_id,
                inviter_id=owner.user_id,
                invitee_id=commenter.user_id,
                status="accepted",
                role="comment",
            ),
            ProjectInvitation(
                project_id=project.project_id,
                inviter_id=owner.user_id,
                invitee_id=reader.user_id,
                status="accepted",
                role="read",
            ),
        )
    )
    db.commit()
    owner_note = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="Owner's source note"),
        db,
        owner,
    )

    with pytest.raises(HTTPException) as reader_cannot_comment:
        annotations.create_document_annotation(
            project.project_id,
            document.document_id,
            AnnotationCreate(note="Not allowed"),
            db,
            reader,
        )
    assert reader_cannot_comment.value.status_code == 403

    with pytest.raises(HTTPException) as cannot_edit_another_author:
        annotations.update_document_annotation(
            project.project_id,
            document.document_id,
            owner_note.annotation_id,
            AnnotationUpdate(note="Changed someone else's note"),
            db,
            commenter,
        )
    assert cannot_edit_another_author.value.status_code == 403

    own_note = annotations.create_document_annotation(
        project.project_id,
        document.document_id,
        AnnotationCreate(note="My comment"),
        db,
        commenter,
    )
    assert own_note.created_by == commenter.user_id
    assert own_note.author_name == "Commenter"
    updated = annotations.update_document_annotation(
        project.project_id,
        document.document_id,
        own_note.annotation_id,
        AnnotationUpdate(note="Edited my comment"),
        db,
        commenter,
    )
    assert updated.note == "Edited my comment"


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
