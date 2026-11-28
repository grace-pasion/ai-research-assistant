import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import (
    ensure_notification_details_column,
    ensure_saved_search_result_count_column,
    ensure_search_query_reproducibility_columns,
)
from app.models import (
    DirectMessage,
    Notification,
    NotificationPreference,
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
    SavedPaperSearchResponse,
    SearchQueryHistoryResponse,
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
        NotificationPreference,
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
    assert duplicate.last_checked_at.replace(tzinfo=timezone.utc) == query.searched_at.replace(
        tzinfo=timezone.utc
    )
    assert duplicate.last_new_result_count is None


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
            searched_at=datetime.now(timezone.utc),
            filters={"limit": 10},
            result_count=2,
            results=[_paper("W123"), _paper("W456")],
        ),
    )

    checked = papers_router.check_saved_search_alerts(project.project_id, db, literature_db, user)
    assert saved.last_new_result_count == 1
    assert saved.last_checked_at is not None
    assert SavedPaperSearchResponse.model_validate(saved).last_new_result_count == 1
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
    assert saved.last_new_result_count == 0
    assert saved.last_checked_at.replace(tzinfo=timezone.utc) == rerun.searched_at
    assert notification_count == 0
    assert checked_again.checked_count == 0
    assert db.query(Notification).count() == 1


def test_failed_saved_search_does_not_update_last_successful_run(saved_search_databases, monkeypatch):
    db, literature_db, user, project, _query, _paper_record = saved_search_databases
    last_checked_at = datetime.now(timezone.utc) - timedelta(days=1)
    saved = SavedPaperSearch(
        project_id=project.project_id,
        user_id=user.user_id,
        query_text="climate models",
        api_provider="openalex",
        alert_enabled=True,
        seen_external_ids=["W123"],
        last_checked_at=last_checked_at,
        last_new_result_count=2,
    )
    db.add(saved)
    db.commit()
    monkeypatch.setattr(
        papers_router,
        "search",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Provider unavailable")),
    )

    with pytest.raises(RuntimeError, match="Provider unavailable"):
        papers_router._run_saved_paper_search(project.project_id, saved, db, literature_db, user)

    assert saved.last_checked_at.replace(tzinfo=timezone.utc) == last_checked_at
    assert saved.last_new_result_count == 2


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


def test_literature_search_records_exact_parameters_and_lists_history(
    saved_search_databases, monkeypatch
):
    db, literature_db, user, project, _query, _paper_record = saved_search_databases
    monkeypatch.setattr(papers_router, "search_papers", lambda *_args: [])

    result = papers_router.search(
        project.project_id,
        "  climate models  ",
        "crossref",
        7,
        db,
        literature_db,
        user,
    )
    history = papers_router.list_search_history(project.project_id, 20, db, user)

    assert result.query == "climate models"
    assert result.provider == "crossref"
    assert result.filters == {"limit": 7}
    assert result.result_count == 0
    assert result.searched_at
    recorded = next(item for item in history if item.query_id == result.query_id)
    assert recorded.query_text == "climate models"
    assert recorded.api_provider == "crossref"
    assert recorded.search_filters == {"limit": 7}
    assert recorded.result_count == 0
    assert recorded.searched_at.replace(tzinfo=timezone.utc) == result.searched_at
    response_record = SearchQueryHistoryResponse.model_validate(recorded)
    assert response_record.searched_at.utcoffset() == timedelta(0)


def test_literature_search_records_provider_result_count(saved_search_databases, monkeypatch):
    db, literature_db, user, project, _query, paper = saved_search_databases
    monkeypatch.setattr(
        papers_router,
        "search_papers",
        lambda *_args: [{"title": "A current study"}],
    )
    monkeypatch.setattr(papers_router, "upsert_paper", lambda _db, _result: paper)
    monkeypatch.setattr(
        papers_router,
        "_paper_response",
        lambda item, _literature_db: _paper(item.external_paper_id),
    )

    result = papers_router.search(
        project.project_id,
        "climate models",
        "openalex",
        10,
        db,
        literature_db,
        user,
    )
    recorded = db.query(SearchQuery).filter(SearchQuery.query_id == result.query_id).one()

    assert result.result_count == 1
    assert recorded.result_count == 1
    assert (
        db.query(SearchQueryResult)
        .filter(SearchQueryResult.query_id == result.query_id)
        .count()
        == 1
    )


def test_saved_search_result_count_column_is_added_to_existing_databases(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-saved-search.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE saved_paper_searches "
                "(saved_search_id CHAR(32) PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO saved_paper_searches (saved_search_id) VALUES ('search-one')")
        )

    ensure_saved_search_result_count_column(engine)
    ensure_saved_search_result_count_column(engine)

    with engine.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                text("PRAGMA table_info(saved_paper_searches)")
            ).mappings()
        }
        assert "last_new_result_count" in columns
        assert connection.execute(
            text("SELECT last_new_result_count FROM saved_paper_searches")
        ).scalar_one() is None
    engine.dispose()


def test_search_history_columns_are_added_and_existing_result_counts_backfilled(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-search.sqlite'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE search_queries (query_id CHAR(32) PRIMARY KEY, "
                "project_id CHAR(32), query_text TEXT, api_provider VARCHAR(32), "
                "searched_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE search_query_results (query_id CHAR(32), paper_id CHAR(32), "
                "PRIMARY KEY (query_id, paper_id))"
            )
        )
        connection.execute(
            text("INSERT INTO search_queries (query_id) VALUES ('query-one'), ('query-two')")
        )
        connection.execute(
            text(
                "INSERT INTO search_query_results (query_id, paper_id) VALUES "
                "('query-one', 'paper-one'), ('query-one', 'paper-two')"
            )
        )

    ensure_search_query_reproducibility_columns(engine)
    ensure_search_query_reproducibility_columns(engine)

    with engine.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info(search_queries)")).mappings()
        }
        counts = connection.execute(
            text(
                "SELECT query_id, search_filters, result_count "
                "FROM search_queries ORDER BY query_id"
            )
        ).all()
    assert {"search_filters", "result_count"} <= columns
    assert [(row.query_id, row.result_count) for row in counts] == [
        ("query-one", 2),
        ("query-two", 0),
    ]
    assert [row.search_filters for row in counts] == ["{}", "{}"]
    engine.dispose()
