import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Author,
    Document,
    Paper,
    PaperAuthor,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    TeamWorkspace,
    TeamWorkspaceMembership,
    User,
)
from app.routers import search
from app.security import get_current_user


@pytest.fixture
def cross_project_search_client(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        TeamWorkspaceMembership,
        ResearchProject,
        ProjectInvitation,
        Document,
        ProjectPaper,
    ):
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(
            email="owner@example.com",
            name="Project owner",
            password_hash="hashed",
        )
        member = User(
            email="member@example.com",
            name="Search member",
            password_hash="hashed",
        )
        outsider = User(
            email="outsider@example.com",
            name="Private owner",
            password_hash="hashed",
        )
        db.add_all((owner, member, outsider))
        db.flush()
        workspace = TeamWorkspace(owner_id=owner.user_id, name="Shared workspace")
        db.add(workspace)
        db.flush()
        invited_project = ResearchProject(
            user_id=owner.user_id,
            project_name="Invited project",
        )
        team_project = ResearchProject(
            user_id=owner.user_id,
            team_workspace_id=workspace.team_workspace_id,
            project_name="Team project",
        )
        private_project = ResearchProject(
            user_id=outsider.user_id,
            project_name="Private project",
        )
        db.add_all((invited_project, team_project, private_project))
        db.flush()
        db.add_all(
            (
                ProjectInvitation(
                    project_id=invited_project.project_id,
                    inviter_id=owner.user_id,
                    invitee_id=member.user_id,
                    status="accepted",
                    role="read",
                ),
                ProjectInvitation(
                    project_id=private_project.project_id,
                    inviter_id=outsider.user_id,
                    invitee_id=member.user_id,
                    status="accepted",
                    role="invalid",
                ),
                TeamWorkspaceMembership(
                    team_workspace_id=workspace.team_workspace_id,
                    user_id=member.user_id,
                    role="member",
                ),
            )
        )

        for project, filename in (
            (invited_project, "invited-neural-study.txt"),
            (team_project, "team-neural-study.txt"),
            (private_project, "private-neural-study.txt"),
        ):
            db.add(
                Document(
                    project_id=project.project_id,
                    filename=filename,
                    file_type="txt",
                    storage_path=filename,
                    file_size=20,
                    extracted_text="Evidence about neural systems.",
                    processing_status="ready",
                    tags=["methods"],
                    custom_metadata={"Author": "Alice Smith", "Year": "2021"},
                )
            )

        paper = Paper(
            external_paper_id="neural-1",
            api_provider="openalex",
            title="Neural systems and learning",
            abstract="Evidence about neural systems.",
            publication_year=2021,
        )
        private_paper = Paper(
            external_paper_id="neural-private",
            api_provider="openalex",
            title="Private neural findings",
            abstract="Private evidence about neural systems.",
            publication_year=2021,
        )
        literature_db.add_all((paper, private_paper))
        literature_db.flush()
        author = Author(
            author_name="Alice Smith",
            external_author_id="alice",
            api_provider="openalex",
        )
        literature_db.add(author)
        literature_db.flush()
        literature_db.add_all(
            (
                PaperAuthor(paper_id=paper.paper_id, author_id=author.author_id, author_order=0),
                PaperAuthor(
                    paper_id=private_paper.paper_id,
                    author_id=author.author_id,
                    author_order=0,
                ),
            )
        )
        db.add_all(
            (
                ProjectPaper(
                    project_id=invited_project.project_id,
                    paper_id=paper.paper_id,
                    tags=["methods"],
                ),
                ProjectPaper(
                    project_id=private_project.project_id,
                    paper_id=private_paper.paper_id,
                    tags=["methods"],
                ),
            )
        )
        db.commit()
        literature_db.commit()

        app = FastAPI()
        app.include_router(search.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_literature_db] = lambda: literature_db
        app.dependency_overrides[get_current_user] = lambda: member
        with TestClient(app) as client:
            yield client, invited_project, team_project, private_project

    research_engine.dispose()
    literature_engine.dispose()


def test_search_filters_sources_across_accessible_projects(cross_project_search_client):
    client, invited_project, team_project, _ = cross_project_search_client

    response = client.get(
        "/api/search",
        params={
            "q": "neural",
            "author": "Alice",
            "year": 2021,
            "tag": "METHODS",
        },
    )

    assert response.status_code == 200
    results = response.json()
    assert {(item["project_id"], item["source_type"]) for item in results} == {
        (str(invited_project.project_id), "paper"),
        (str(invited_project.project_id), "document"),
        (str(team_project.project_id), "document"),
    }
    assert all(item["authors"] == ["Alice Smith"] for item in results)
    assert all(item["year"] == 2021 and item["tags"] == ["methods"] for item in results)


def test_search_project_and_source_filters_and_access_boundaries(
    cross_project_search_client,
):
    client, invited_project, team_project, private_project = cross_project_search_client

    paper_response = client.get(
        "/api/search",
        params={
            "q": "neural",
            "project_id": str(invited_project.project_id),
            "source_type": "paper",
        },
    )
    assert paper_response.status_code == 200
    assert len(paper_response.json()) == 1
    assert paper_response.json()[0]["source_type"] == "paper"

    team_response = client.get(
        "/api/search",
        params={"q": "neural", "project_id": str(team_project.project_id)},
    )
    assert team_response.status_code == 200
    assert {item["source_type"] for item in team_response.json()} == {"document"}

    private_response = client.get(
        "/api/search",
        params={"q": "neural", "project_id": str(private_project.project_id)},
    )
    assert private_response.status_code == 404

    all_results = client.get("/api/search", params={"q": "neural"}).json()
    assert all(item["project_id"] != str(private_project.project_id) for item in all_results)

    first_page = client.get(
        "/api/search",
        params={"q": "neural", "limit": 1},
    ).json()
    second_page = client.get(
        "/api/search",
        params={"q": "neural", "limit": 1, "offset": 1},
    ).json()
    assert len(first_page) == len(second_page) == 1
    assert first_page[0]["source_id"] != second_page[0]["source_id"]
