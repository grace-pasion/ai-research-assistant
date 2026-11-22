import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import ensure_project_paper_screening_columns
from app.models import (
    Author,
    Paper,
    PaperAuthor,
    ProjectPaper,
    ResearchProject,
    User,
    UserActivity,
)
from app.routers.papers import list_saved_papers, update_paper_screening
from app.schemas import PaperScreeningUpdate


@pytest.fixture
def screening_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (User, ResearchProject, ProjectPaper, UserActivity):
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)
    with Session(research_engine) as research_db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        research_db.add(user)
        research_db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        research_db.add(project)
        research_db.flush()
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="A screening study",
            abstract="Study abstract",
        )
        literature_db.add(paper)
        literature_db.flush()
        relation = ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id)
        research_db.add(relation)
        research_db.commit()
        literature_db.commit()
        yield research_db, literature_db, user, project, paper
    research_engine.dispose()
    literature_engine.dispose()


def test_screening_status_and_note_persist_and_appear_in_project_papers(screening_databases):
    db, literature_db, user, project, paper = screening_databases

    updated = update_paper_screening(
        project.project_id,
        paper.paper_id,
        PaperScreeningUpdate(screening_status="include", screening_note="  Strong evidence  "),
        db,
        user,
    )
    listed = list_saved_papers(project.project_id, db, literature_db, user)

    assert updated.screening_status == "include"
    assert updated.screening_note == "Strong evidence"
    assert listed[0].screening_status == "include"
    assert listed[0].screening_note == "Strong evidence"
    assert listed[0].saved is True

    with Session(db.get_bind()) as fresh_db:
        persisted = fresh_db.get(ProjectPaper, (project.project_id, paper.paper_id))
        assert persisted is not None
        assert persisted.screening_status == "include"
        assert persisted.screening_note == "Strong evidence"


def test_screening_defaults_to_unread_and_note_can_be_cleared(screening_databases):
    db, literature_db, user, project, paper = screening_databases

    assert list_saved_papers(project.project_id, db, literature_db, user)[0].screening_status == "unread"
    updated = update_paper_screening(
        project.project_id,
        paper.paper_id,
        PaperScreeningUpdate(screening_status="unread", screening_note=""),
        db,
        user,
    )

    assert updated.screening_status == "unread"
    assert updated.screening_note == ""


def test_undecided_is_a_valid_persisted_screening_status(screening_databases):
    db, literature_db, user, project, paper = screening_databases

    updated = update_paper_screening(
        project.project_id,
        paper.paper_id,
        PaperScreeningUpdate(screening_status="undecided", screening_note="Needs team discussion"),
        db,
        user,
    )
    listed = list_saved_papers(project.project_id, db, literature_db, user)

    assert updated.screening_status == "undecided"
    assert listed[0].screening_status == "undecided"
    assert listed[0].screening_note == "Needs team discussion"


def test_screening_requires_owned_project_and_saved_paper(screening_databases):
    db, _, user, project, paper = screening_databases

    with pytest.raises(HTTPException) as missing_paper:
        update_paper_screening(
            project.project_id, uuid.uuid4(), PaperScreeningUpdate(screening_status="exclude"), db, user
        )
    assert missing_paper.value.status_code == 404

    other_user = User(
        user_id=uuid.uuid4(),
        email="other@example.com",
        name="Other",
        password_hash="hashed",
    )
    with pytest.raises(HTTPException) as other_owner:
        update_paper_screening(
            project.project_id, paper.paper_id, PaperScreeningUpdate(screening_status="exclude"), db, other_user
        )
    assert other_owner.value.status_code == 404


def test_existing_project_paper_table_gets_screening_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE project_papers (project_id CHAR(32), paper_id CHAR(32), "
                "relevance_score FLOAT, relationship_type VARCHAR(64), added_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO project_papers "
                "(project_id, paper_id, relationship_type) VALUES ('project', 'paper', 'saved')"
            )
        )

    ensure_project_paper_screening_columns(engine)

    with engine.connect() as connection:
        columns = {row["name"] for row in connection.execute(text("PRAGMA table_info(project_papers)")).mappings()}
        assert {"screening_status", "screening_note"} <= columns
        row = connection.execute(
            text("SELECT screening_status, screening_note FROM project_papers")
        ).first()
        assert row == ("unread", "")
    engine.dispose()


def test_screening_update_rejects_unknown_decisions_and_long_notes():
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="maybe")
    assert PaperScreeningUpdate(screening_status="undecided").screening_status == "undecided"
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="include", screening_note="x" * 501)
