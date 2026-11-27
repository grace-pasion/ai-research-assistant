import uuid
import csv
import io
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import ensure_project_paper_screening_columns, get_db, get_literature_db
from app.models import (
    Author,
    Paper,
    PaperAuthor,
    PaperScreeningDecision,
    ProjectActivity,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    SystematicReviewWorkspace,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import papers as papers_router
from app.routers.papers import (
    bulk_update_paper_screening,
    export_screening_csv,
    export_systematic_review_csv,
    get_systematic_review,
    list_saved_papers,
    save_paper,
    save_systematic_review,
    update_paper_screening,
    update_reviewer_screening_decision,
)
from app.schemas import (
    PaperScreeningBulkUpdate,
    PaperScreeningDecisionUpdate,
    PaperScreeningUpdate,
    SystematicReviewUpdate,
)
from sqlalchemy.exc import IntegrityError
from app.security import get_current_user


@pytest.fixture
def screening_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        ProjectPaper,
        PaperScreeningDecision,
        SystematicReviewWorkspace,
        UserActivity,
        ProjectActivity,
    ):
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


def test_saved_paper_list_returns_project_tags_and_custom_metadata(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    relation = db.get(ProjectPaper, (project.project_id, paper.paper_id))
    relation.tags = ["methodology"]
    relation.custom_metadata = {"Study design": "Cohort"}
    db.commit()

    listed = list_saved_papers(project.project_id, db, literature_db, user)

    assert listed[0].tags == ["methodology"]
    assert listed[0].metadata == {"Study design": "Cohort"}


def test_concurrent_save_of_same_paper_is_idempotent(screening_databases, monkeypatch):
    db, _literature_db, user, project, paper = screening_databases
    relation = db.get(ProjectPaper, (project.project_id, paper.paper_id))
    db.delete(relation)
    db.commit()

    def competing_commit():
        db.rollback()
        with Session(db.get_bind()) as competing_db:
            competing_db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
            competing_db.commit()
        raise IntegrityError("insert", {}, Exception("duplicate project paper"))

    monkeypatch.setattr(db, "commit", competing_commit)

    save_paper(project.project_id, paper.paper_id, db, _literature_db, user)

    assert db.get(ProjectPaper, (project.project_id, paper.paper_id)) is not None


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
            project.project_id, uuid.uuid4(), PaperScreeningUpdate(screening_status="include"), db, user
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
            project.project_id, paper.paper_id, PaperScreeningUpdate(screening_status="include"), db, other_user
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
        assert {"screening_status", "screening_note", "screening_exclusion_reason"} <= columns
        row = connection.execute(
            text(
                "SELECT screening_status, screening_note, screening_exclusion_reason "
                "FROM project_papers"
            )
        ).first()
        assert row == ("unread", "", None)
    engine.dispose()


def test_screening_update_rejects_unknown_decisions_and_long_notes():
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="maybe")
    assert PaperScreeningUpdate(screening_status="undecided").screening_status == "undecided"
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="include", screening_note="x" * 501)
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="exclude")
    with pytest.raises(ValidationError):
        PaperScreeningUpdate(screening_status="exclude", exclusion_reason="other")
    assert PaperScreeningUpdate(
        screening_status="exclude",
        exclusion_reason="other",
        screening_note="Outside our research question",
    ).exclusion_reason == "other"


def test_reviewer_decisions_keep_identity_and_flag_status_and_reason_disagreements(
    screening_databases,
):
    db, literature_db, owner, project, paper = screening_databases
    reviewer = User(
        email="reviewer@example.com",
        name="Second reviewer",
        password_hash="hashed",
    )
    db.add(reviewer)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=reviewer.user_id,
            status="accepted",
            role="edit",
        )
    )
    db.commit()

    update_reviewer_screening_decision(
        project.project_id,
        paper.paper_id,
        PaperScreeningDecisionUpdate(screening_status="include"),
        db,
        owner,
    )
    update_reviewer_screening_decision(
        project.project_id,
        paper.paper_id,
        PaperScreeningDecisionUpdate(
            screening_status="exclude",
            exclusion_reason="wrong_population",
        ),
        db,
        reviewer,
    )

    listed = list_saved_papers(project.project_id, db, literature_db, owner)[0]
    assert listed.screening_disagreement is True
    assert {decision.user_name for decision in listed.screening_decisions} == {
        "Reader",
        "Second reviewer",
    }

    update_reviewer_screening_decision(
        project.project_id,
        paper.paper_id,
        PaperScreeningDecisionUpdate(
            screening_status="exclude",
            exclusion_reason="wrong_outcome",
        ),
        db,
        owner,
    )
    listed = list_saved_papers(project.project_id, db, literature_db, owner)[0]
    assert listed.screening_disagreement is True

    update_reviewer_screening_decision(
        project.project_id,
        paper.paper_id,
        PaperScreeningDecisionUpdate(
            screening_status="exclude",
            exclusion_reason="wrong_outcome",
        ),
        db,
        reviewer,
    )
    listed = list_saved_papers(project.project_id, db, literature_db, owner)[0]
    assert listed.screening_disagreement is False
    assert db.get(PaperScreeningDecision, (project.project_id, paper.paper_id, owner.user_id))
    assert db.get(ProjectPaper, (project.project_id, paper.paper_id)).screening_status == "unread"


def test_bulk_screening_updates_saved_papers_and_preserves_notes_by_default(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    second_paper = Paper(
        external_paper_id="paper-2",
        api_provider="openalex",
        title="A second screening study",
    )
    literature_db.add(second_paper)
    literature_db.flush()
    db.add(ProjectPaper(project_id=project.project_id, paper_id=second_paper.paper_id))
    relation = db.get(ProjectPaper, (project.project_id, paper.paper_id))
    relation.screening_note = "Keep this reason"
    db.commit()
    literature_db.commit()

    result = bulk_update_paper_screening(
        project.project_id,
        PaperScreeningBulkUpdate(
            paper_ids=[paper.paper_id, second_paper.paper_id],
            screening_status="include",
        ),
        db,
        user,
    )

    assert result.updated_count == 2
    assert relation.screening_status == "include"
    assert relation.screening_note == "Keep this reason"
    assert db.get(ProjectPaper, (project.project_id, second_paper.paper_id)).screening_status == "include"


def test_bulk_screening_rejects_mixed_saved_and_unsaved_papers_without_partial_update(screening_databases):
    db, _, user, project, paper = screening_databases
    missing_paper_id = uuid.uuid4()

    with pytest.raises(HTTPException) as error:
        bulk_update_paper_screening(
            project.project_id,
            PaperScreeningBulkUpdate(
                paper_ids=[paper.paper_id, missing_paper_id],
                screening_status="exclude",
                exclusion_reason="wrong_population",
            ),
            db,
            user,
        )

    assert error.value.status_code == 404
    assert db.get(ProjectPaper, (project.project_id, paper.paper_id)).screening_status == "unread"


def test_screening_csv_exports_decisions_and_neutralizes_spreadsheet_formulas(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    paper.title = "=HYPERLINK(\"https://example.test\")"
    db.get(ProjectPaper, (project.project_id, paper.paper_id)).screening_note = "  - formula"
    literature_db.commit()
    db.commit()

    response = export_screening_csv(project.project_id, db, literature_db, user)
    rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))

    assert response.headers["content-disposition"] == 'attachment; filename="screening.csv"'
    assert rows[0]["title"].startswith("'=")
    assert rows[0]["screening_status"] == "unread"
    assert rows[0]["screening_note"] == "'  - formula"


def test_screening_exports_include_exclusion_reason_and_named_reviewer_trail(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    update_paper_screening(
        project.project_id,
        paper.paper_id,
        PaperScreeningUpdate(
            screening_status="exclude",
            screening_note="Outside the target population",
            exclusion_reason="wrong_population",
        ),
        db,
        user,
    )
    update_reviewer_screening_decision(
        project.project_id,
        paper.paper_id,
        PaperScreeningDecisionUpdate(screening_status="include"),
        db,
        user,
    )

    screening = export_screening_csv(project.project_id, db, literature_db, user)
    screening_rows = list(csv.DictReader(io.StringIO(screening.body.decode("utf-8"))))
    decision_trail = json.loads(screening_rows[0]["reviewer_decisions"])
    assert screening_rows[0]["screening_exclusion_reason"] == "wrong_population"
    assert screening_rows[0]["reviewer_disagreement"] == "no"
    assert decision_trail[0]["user_name"] == "Reader"
    assert decision_trail[0]["screening_status"] == "include"

    report = export_systematic_review_csv(project.project_id, db, literature_db, user)
    report_rows = list(csv.reader(io.StringIO(report.body.decode("utf-8"))))
    assert len(report_rows[0]) == len(report_rows[1]) == len(report_rows[2])
    assert report_rows[2][19] == "wrong_population"
    assert json.loads(report_rows[2][21])[0]["user_name"] == "Reader"


def test_systematic_review_persists_protocol_and_reports_shared_screening_counts(screening_databases):
    db, _literature_db, user, project, paper = screening_databases

    initial = get_systematic_review(project.project_id, db, user)
    assert initial.review_question == ""
    assert initial.screening_counts.total == 1
    assert initial.screening_counts.unread == 1
    assert initial.screening_counts.reviewed == 0

    saved = save_systematic_review(
        project.project_id,
        SystematicReviewUpdate(
            review_question="  Does the intervention improve outcomes?  ",
            protocol="  Include controlled studies.\nExclude editorials.  ",
            expected_updated_at=initial.updated_at,
        ),
        db,
        user,
    )
    assert saved.review_question == "Does the intervention improve outcomes?"
    assert saved.protocol == "Include controlled studies.\nExclude editorials."
    assert saved.updated_at is not None
    assert saved.screening_counts.total == 1

    update_paper_screening(
        project.project_id,
        paper.paper_id,
        PaperScreeningUpdate(screening_status="include"),
        db,
        user,
    )
    refreshed = get_systematic_review(project.project_id, db, user)
    assert refreshed.screening_counts.include == 1
    assert refreshed.screening_counts.reviewed == 1

    with pytest.raises(HTTPException) as stale:
        save_systematic_review(
            project.project_id,
            SystematicReviewUpdate(
                review_question="Stale question",
                protocol="Stale protocol",
                expected_updated_at=initial.updated_at,
            ),
            db,
            user,
        )
    assert stale.value.status_code == 409
    assert get_systematic_review(project.project_id, db, user).review_question == saved.review_question


def test_systematic_review_is_shared_read_only_to_commenters(screening_databases):
    db, _, owner, project, _paper = screening_databases
    commenter = User(
        email="commenter@example.com",
        name="Commenter",
        password_hash="hashed",
    )
    db.add(commenter)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=commenter.user_id,
            status="accepted",
            role="comment",
        )
    )
    db.commit()

    assert get_systematic_review(project.project_id, db, commenter).review_question == ""
    with pytest.raises(HTTPException) as error:
        save_systematic_review(
            project.project_id,
            SystematicReviewUpdate(
                review_question="Question",
                protocol="Protocol",
                expected_updated_at=None,
            ),
            db,
            commenter,
        )
    assert error.value.status_code == 403

    editor = User(
        email="editor@example.com",
        name="Editor",
        password_hash="hashed",
    )
    db.add(editor)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=editor.user_id,
            status="accepted",
            role="edit",
        )
    )
    db.commit()
    saved = save_systematic_review(
        project.project_id,
        SystematicReviewUpdate(
            review_question="Editor question",
            protocol="Editor protocol",
            expected_updated_at=None,
        ),
        db,
        editor,
    )
    assert saved.review_question == "Editor question"


def test_review_report_exports_metadata_decisions_and_safe_counts(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    paper.title = '=HYPERLINK("https://example.test")'
    db.get(ProjectPaper, (project.project_id, paper.paper_id)).screening_note = "  - formula"
    db.add(
        SystematicReviewWorkspace(
            project_id=project.project_id,
            review_question="=SUM(1,1)",
            protocol="@include controlled studies",
            updated_by=user.user_id,
        )
    )
    literature_db.commit()
    db.commit()

    response = export_systematic_review_csv(project.project_id, db, literature_db, user)
    rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))
    summary, paper_row = rows

    assert response.headers["content-disposition"] == (
        'attachment; filename="systematic-review-report.csv"'
    )
    assert summary["record_type"] == "summary"
    assert summary["review_question"] == "'=SUM(1,1)"
    assert summary["protocol"] == "'@include controlled studies"
    assert summary["total_papers"] == "1"
    assert summary["unread_count"] == "1"
    assert summary["reviewed_papers"] == "0"
    assert paper_row["record_type"] == "paper"
    assert paper_row["title"].startswith("'=")
    assert paper_row["screening_status"] == "unread"
    assert paper_row["screening_note"] == "'  - formula"


def test_review_report_exports_zero_counts_without_saved_papers(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    db.delete(db.get(ProjectPaper, (project.project_id, paper.paper_id)))
    db.commit()

    response = export_systematic_review_csv(project.project_id, db, literature_db, user)
    rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))

    assert len(rows) == 1
    assert rows[0]["record_type"] == "summary"
    assert rows[0]["total_papers"] == "0"
    assert rows[0]["unread_count"] == "0"


def test_systematic_review_http_routes_round_trip_and_export(screening_databases):
    db, literature_db, user, project, paper = screening_databases
    app = FastAPI()
    app.include_router(papers_router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_literature_db] = lambda: literature_db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as client:
        path = f"/api/projects/{project.project_id}/papers/review"
        initial = client.get(path)
        assert initial.status_code == 200
        assert initial.json()["screening_counts"]["total"] == 1

        updated = client.put(
            path,
            json={
                "review_question": "Can the method improve outcomes?",
                "protocol": "Include randomized studies.",
                "expected_updated_at": None,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["review_question"] == "Can the method improve outcomes?"

        reviewer_decision = client.patch(
            f"/api/projects/{project.project_id}/papers/{paper.paper_id}/screening/decision",
            json={
                "screening_status": "exclude",
                "exclusion_reason": "wrong_study_design",
                "screening_note": "",
            },
        )
        assert reviewer_decision.status_code == 200
        assert reviewer_decision.json()["user_name"] == "Reader"
        assert reviewer_decision.json()["exclusion_reason"] == "wrong_study_design"
        assert reviewer_decision.json()["updated_at"]
        listed = client.get(f"/api/projects/{project.project_id}/papers")
        assert listed.status_code == 200
        assert listed.json()[0]["screening_status"] == "unread"
        assert listed.json()[0]["screening_decisions"][0]["user_id"] == str(user.user_id)

        report = client.get(f"{path}/export")
        assert report.status_code == 200
        assert report.headers["content-type"] == "text/csv; charset=utf-8"
        assert "Can the method improve outcomes?" in report.text


def test_bulk_screening_requires_at_least_one_paper():
    with pytest.raises(ValidationError):
        PaperScreeningBulkUpdate(paper_ids=[], screening_status="include")
