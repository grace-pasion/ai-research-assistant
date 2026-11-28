from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Conversation, Message, ProjectInvitation, ResearchProject, User
from app.routers import assistant
from app.security import get_current_user


@pytest.fixture
def assistant_conversation_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'assistant-conversations.sqlite'}")
    for model in (User, ResearchProject, ProjectInvitation, Conversation, Message):
        model.__table__.create(engine)

    with Session(engine) as db:
        owner = User(email="owner@example.com", name="Owner", password_hash="hashed")
        reader = User(email="reader@example.com", name="Reader", password_hash="hashed")
        db.add_all((owner, reader))
        db.flush()
        project = ResearchProject(user_id=owner.user_id, project_name="Research project")
        other_project = ResearchProject(user_id=owner.user_id, project_name="Other project")
        db.add_all((project, other_project))
        db.flush()
        conversation = Conversation(
            user_id=owner.user_id,
            project_id=project.project_id,
            title="Original question",
            updated_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(conversation)
        db.flush()
        message = Message(
            conversation_id=conversation.conversation_id,
            role="user",
            content="Original question",
        )
        db.add_all(
            (
                message,
                ProjectInvitation(
                    project_id=project.project_id,
                    inviter_id=owner.user_id,
                    invitee_id=reader.user_id,
                    role="read",
                    status="accepted",
                ),
            )
        )
        db.commit()

        active_user = {"user": owner}
        app = FastAPI()
        app.include_router(assistant.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: active_user["user"]
        with TestClient(app) as client:
            yield {
                "client": client,
                "active_user": active_user,
                "owner": owner,
                "reader": reader,
                "project": project,
                "other_project": other_project,
                "conversation": conversation,
                "message": message,
                "db": db,
            }

    engine.dispose()


def test_conversation_rename_updates_title_and_preserves_messages(assistant_conversation_client):
    data = assistant_conversation_client
    original_updated_at = data["conversation"].updated_at
    response = data["client"].patch(
        f"/api/projects/{data['project'].project_id}/assistant/conversations/"
        f"{data['conversation'].conversation_id}",
        json={"title": "  A clearer title  "},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "A clearer title"
    assert datetime.fromisoformat(response.json()["updated_at"]) > original_updated_at

    listed = data["client"].get(
        f"/api/projects/{data['project'].project_id}/assistant/conversations"
    )
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "A clearer title"
    assert data["db"].scalar(
        select(Message.content).where(Message.message_id == data["message"].message_id)
    ) == "Original question"


def test_conversation_rename_accepts_a_200_character_title(assistant_conversation_client):
    data = assistant_conversation_client
    title = "x" * 200
    response = data["client"].patch(
        f"/api/projects/{data['project'].project_id}/assistant/conversations/"
        f"{data['conversation'].conversation_id}",
        json={"title": title},
    )

    assert response.status_code == 200
    assert response.json()["title"] == title


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_conversation_rename_rejects_invalid_titles(assistant_conversation_client, title):
    data = assistant_conversation_client
    response = data["client"].patch(
        f"/api/projects/{data['project'].project_id}/assistant/conversations/"
        f"{data['conversation'].conversation_id}",
        json={"title": title},
    )

    assert response.status_code == 422
    assert data["db"].get(Conversation, data["conversation"].conversation_id).title == "Original question"


def test_conversation_rename_is_private_to_the_author(assistant_conversation_client):
    data = assistant_conversation_client
    data["active_user"]["user"] = data["reader"]

    response = data["client"].patch(
        f"/api/projects/{data['project'].project_id}/assistant/conversations/"
        f"{data['conversation'].conversation_id}",
        json={"title": "Reader's title"},
    )

    assert response.status_code == 404
    assert data["db"].get(Conversation, data["conversation"].conversation_id).title == "Original question"


def test_conversation_rename_rejects_a_different_project(assistant_conversation_client):
    data = assistant_conversation_client
    response = data["client"].patch(
        f"/api/projects/{data['other_project'].project_id}/assistant/conversations/"
        f"{data['conversation'].conversation_id}",
        json={"title": "Wrong project"},
    )

    assert response.status_code == 404
    assert data["db"].get(Conversation, data["conversation"].conversation_id).title == "Original question"
