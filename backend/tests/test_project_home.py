from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ProjectActivity,
    ProjectInvitation,
    ResearchProject,
    User,
    UserActivity,
)
from app.routers import project_home
from app.security import get_current_user
from app.services.audit import record_activity


@pytest.fixture
def project_home_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'project-home.sqlite'}")
    for model in (User, ResearchProject, ProjectInvitation, UserActivity, ProjectActivity):
        model.__table__.create(engine)

    with Session(engine) as db:
        owner = User(email="owner@example.com", name="Project owner", password_hash="hashed")
        reader = User(email="reader@example.com", name="Project reader", password_hash="hashed")
        outsider = User(email="outsider@example.com", name="Outsider", password_hash="hashed")
        db.add_all((owner, reader, outsider))
        db.flush()
        project = ResearchProject(user_id=owner.user_id, project_name="Research project")
        other_project = ResearchProject(user_id=owner.user_id, project_name="Other project")
        db.add_all((project, other_project))
        db.flush()
        db.add(
            ProjectInvitation(
                project_id=project.project_id,
                inviter_id=owner.user_id,
                invitee_id=reader.user_id,
                role="read",
                status="accepted",
            )
        )
        base_time = datetime.now(timezone.utc) - timedelta(days=1)
        db.add_all(
            ProjectActivity(
                project_id=project.project_id,
                actor_id=owner.user_id,
                action=f"document.change_{index}",
                created_at=base_time + timedelta(minutes=index),
            )
            for index in range(13)
        )
        db.add(
            ProjectActivity(
                project_id=other_project.project_id,
                actor_id=owner.user_id,
                action="other.project.change",
                created_at=base_time + timedelta(days=1),
            )
        )
        record_activity(
            db,
            owner.user_id,
            "project.updated",
            project_id=project.project_id,
        )
        db.commit()

        active_user = {"user": owner}
        app = FastAPI()
        app.include_router(project_home.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: active_user["user"]
        with TestClient(app) as client:
            yield {
                "client": client,
                "active_user": active_user,
                "owner": owner,
                "reader": reader,
                "outsider": outsider,
                "project": project,
                "other_project": other_project,
            }

    engine.dispose()


def test_project_home_activity_is_scoped_limited_and_readable_by_collaborators(
    project_home_client,
):
    client = project_home_client["client"]
    project_id = project_home_client["project"].project_id
    response = client.get(f"/api/projects/{project_id}/home/activity")

    assert response.status_code == 200
    activities = response.json()
    assert len(activities) == 12
    assert activities[0]["action"] == "project.updated"
    assert activities[0]["actor_name"] == "Project owner"
    assert all(not item["action"].startswith("other.") for item in activities)

    project_home_client["active_user"]["user"] = project_home_client["reader"]
    reader_response = client.get(f"/api/projects/{project_id}/home/activity")
    assert reader_response.status_code == 200

    project_home_client["active_user"]["user"] = project_home_client["outsider"]
    outsider_response = client.get(f"/api/projects/{project_id}/home/activity")
    assert outsider_response.status_code == 404
