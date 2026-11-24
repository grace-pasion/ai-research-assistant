import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import ensure_notification_details_column
from app.models import (
    DirectMessage,
    Notification,
    Paper,
    ProjectInvitation,
    ResearchProject,
    SavedPaperSearch,
    SearchQuery,
    SearchQueryResult,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import papers as papers_router
from app.routers.collaboration import list_notifications
from app.schemas import (
    PaperResponse,
    PaperSearchResponse,
    SavedPaperSearchCreate,
)


@pytest.fixture
def saved_search_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        DirectMessage,
        Notification,
        SearchQuery,
        SearchQueryResult,
        SavedPaperSearch,
        UserActivity,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)
    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        db.add(user)
        db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        db.add(project)
        db.flush()
        paper = Paper(
            external_paper_id="W123",
            api_provider="openalex",
            title="A current study",
        )
        literature_db.add(paper)
        literature_db.flush()
        query = SearchQuery(project_id=project.project_id, query_text="climate models", api_provider="openalex")
        db.add(query)
        db.flush()
        db.add(SearchQueryResult(query_id=query.query_id, paper_id=paper.paper_id))
        db.commit()
        literature_db.commit()
        yield db, literature_db, user, project, query, paper
    research_engine.dispose()
    literature_engine.dispose()


def _paper(external_paper_id: str) -> PaperResponse:
    return PaperResponse(
        paper_id=uuid.uuid4(),
        external_paper_id=external_paper_id,
        api_provider="openalex",
        title=f"Study {external_paper_id}",
        abstract=None,
        publication_year=None,
        doi=None,
        paper_url=None,
        venue=None,
        citation_count=None,
        authors=[],
        saved=False,
    )


def test_saved_search_uses_search_history_as_baseline_and_is_idempotent(saved_search_databases):
    db, literature_db, user, project, query, paper = saved_search_databases

    saved = papers_router.create_saved_search(
        project.project_id,
        SavedPaperSearchCreate(query_id=query.query_id),
        db,
        literature_db,
        user,
    )
    duplicate = papers_router.create_saved_search(
        project.project_id,
        SavedPaperSearchCreate(query_id=query.query_id, alert_enabled=True),
        db,
        literature_db,
        user,
    )

    assert saved.saved_search_id == duplicate.saved_search_id
    assert duplicate.alert_enabled is True
    assert duplicate.seen_external_ids == [paper.external_paper_id]


def test_due_alert_records_new_matches_once_and_respects_six_hour_cadence(
    saved_search_databases, monkeypatch
):
    db, literature_db, user, project, _query, _paper_record = saved_search_databases
    saved = SavedPaperSearch(
        project_id=project.project_id,
        user_id=user.user_id,
        query_text="climate models",
        api_provider="openalex",
        alert_enabled=True,
        seen_external_ids=["W123"],
        last_checked_at=datetime.now(timezone.utc) - timedelta(hours=7),
    )
    db.add(saved)
    db.commit()

    monkeypatch.setattr(
        papers_router,
        "search",
        lambda _project_id, query, provider, _limit, *_args: PaperSearchResponse(
            query_id=uuid.uuid4(),
            provider=provider,
            query=query,
            results=[_paper("W123"), _paper("W456")],
        ),
    )

    checked = papers_router.check_saved_search_alerts(project.project_id, db, literature_db, user)
    notification = db.query(Notification).one()
    inbox_notifications = list_notifications(db, user)
    rerun, new_count, notification_count = papers_router._run_saved_paper_search(
        project.project_id, saved, db, literature_db, user
    )
    checked_again = papers_router.check_saved_search_alerts(project.project_id, db, literature_db, user)

    assert checked.checked_count == 1
    assert checked.notifications_created == 1
    assert notification.details == {
        "query": "climate models",
        "provider": "openalex",
        "new_result_count": 1,
    }
    assert inbox_notifications[0]["details"] == notification.details
    assert rerun.query == "climate models"
    assert new_count == 0
    assert notification_count == 0
    assert checked_again.checked_count == 0
    assert db.query(Notification).count() == 1


def test_notification_details_column_is_added_to_existing_databases(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE notifications (notification_id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO notifications (notification_id) VALUES ('legacy')"))

    ensure_notification_details_column(engine)

    with engine.connect() as connection:
        columns = {row["name"] for row in connection.execute(text("PRAGMA table_info(notifications)")).mappings()}
        assert "details" in columns
        assert connection.execute(text("SELECT details FROM notifications")).scalar_one() == "{}"
    engine.dispose()
