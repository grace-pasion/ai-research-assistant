import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Document,
    Paper,
    ProjectCollection,
    ProjectCollectionItem,
    ProjectActivity,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    User,
    UserActivity,
)
from app.routers import collections, papers
from app.security import get_current_user


@pytest.fixture
def collection_client(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        UserActivity,
        ProjectActivity,
        ResearchProject,
        ProjectInvitation,
        Document,
        ProjectPaper,
        ProjectCollection,
        ProjectCollectionItem,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(
            email="owner@example.com",
            name="Project owner",
            password_hash="hashed",
        )
        reader = User(
            email="reader@example.com",
            name="Project reader",
            password_hash="hashed",
        )
        outsider = User(
            email="outsider@example.com",
            name="Outsider",
            password_hash="hashed",
        )
        db.add_all((owner, reader, outsider))
        db.flush()
        project = ResearchProject(user_id=owner.user_id, project_name="Research project")
        other_project = ResearchProject(user_id=owner.user_id, project_name="Other project")
        db.add_all((project, other_project))
        db.flush()
        document = Document(
            project_id=project.project_id,
            filename="background.pdf",
            file_type="pdf",
            storage_path="background.pdf",
            file_size=20,
            extracted_text="Background source.",
            processing_status="ready",
        )
        other_document = Document(
            project_id=other_project.project_id,
            filename="private-to-project.txt",
            file_type="txt",
            storage_path="private-to-project.txt",
            file_size=20,
            extracted_text="Other project source.",
            processing_status="ready",
        )
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="Methods paper",
            abstract="Methods abstract.",
        )
        other_paper = Paper(
            external_paper_id="paper-2",
            api_provider="openalex",
            title="Other project paper",
            abstract="Other abstract.",
        )
        db.add_all((document, other_document))
        literature_db.add_all((paper, other_paper))
        db.flush()
        literature_db.flush()
        db.add_all(
            (
                ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id),
                ProjectPaper(project_id=other_project.project_id, paper_id=other_paper.paper_id),
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
        literature_db.commit()

        active_user = {"user": owner}
        app = FastAPI()
        app.include_router(collections.router)
        app.include_router(papers.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_literature_db] = lambda: literature_db
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
                "document": document,
                "other_document": other_document,
                "paper": paper,
                "other_paper": other_paper,
            }

    research_engine.dispose()
    literature_engine.dispose()


def _create_collection(client: TestClient, project_id: str, name: str = "Background"):
    return client.post(
        f"/api/projects/{project_id}/collections",
        json={"name": name},
    )


def test_collection_lifecycle_and_saved_paper_cleanup(collection_client):
    client = collection_client["client"]
    project = collection_client["project"]
    document = collection_client["document"]
    paper = collection_client["paper"]

    created = _create_collection(client, str(project.project_id), "  Background  ")
    assert created.status_code == 201
    collection = created.json()
    assert collection["name"] == "Background"
    assert collection["items"] == []

    duplicate_name = _create_collection(client, str(project.project_id), "background")
    assert duplicate_name.status_code == 409

    for source_type, source_id in (
        ("document", document.document_id),
        ("paper", paper.paper_id),
    ):
        response = client.post(
            f"/api/projects/{project.project_id}/collections/{collection['collection_id']}/items",
            json={"source_type": source_type, "source_id": str(source_id)},
        )
        assert response.status_code == 201

    duplicate_item = client.post(
        f"/api/projects/{project.project_id}/collections/{collection['collection_id']}/items",
        json={"source_type": "document", "source_id": str(document.document_id)},
    )
    assert duplicate_item.status_code == 409
    duplicate_paper = client.post(
        f"/api/projects/{project.project_id}/collections/{collection['collection_id']}/items",
        json={"source_type": "paper", "source_id": str(paper.paper_id)},
    )
    assert duplicate_paper.status_code == 409

    cross_project_document = client.post(
        f"/api/projects/{project.project_id}/collections/{collection['collection_id']}/items",
        json={
            "source_type": "document",
            "source_id": str(collection_client["other_document"].document_id),
        },
    )
    assert cross_project_document.status_code == 404

    listed = client.get(f"/api/projects/{project.project_id}/collections")
    assert listed.status_code == 200
    listed_collection = listed.json()[0]
    assert {item["source_title"] for item in listed_collection["items"]} == {
        "background.pdf",
        "Methods paper",
    }

    removed_paper = client.delete(
        f"/api/projects/{project.project_id}/papers/{paper.paper_id}/save"
    )
    assert removed_paper.status_code == 204
    remaining = client.get(f"/api/projects/{project.project_id}/collections").json()[0]
    assert [item["source_title"] for item in remaining["items"]] == ["background.pdf"]

    item_id = remaining["items"][0]["item_id"]
    removed_document = client.delete(
        f"/api/projects/{project.project_id}/collections/{collection['collection_id']}/items/{item_id}"
    )
    assert removed_document.status_code == 204

    deleted = client.delete(
        f"/api/projects/{project.project_id}/collections/{collection['collection_id']}"
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/{project.project_id}/collections").json() == []


def test_collection_rename_validation_and_paper_project_boundary(collection_client):
    client = collection_client["client"]
    project = collection_client["project"]
    collection_id = _create_collection(client, str(project.project_id), "Methods").json()[
        "collection_id"
    ]
    other_collection_id = _create_collection(
        client, str(project.project_id), "Read next"
    ).json()["collection_id"]

    duplicate_rename = client.patch(
        f"/api/projects/{project.project_id}/collections/{other_collection_id}",
        json={"name": " methods "},
    )
    assert duplicate_rename.status_code == 409

    renamed = client.patch(
        f"/api/projects/{project.project_id}/collections/{other_collection_id}",
        json={"name": "  Background notes  "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Background notes"

    blank_name = client.post(
        f"/api/projects/{project.project_id}/collections",
        json={"name": "  "},
    )
    assert blank_name.status_code == 422

    invalid_paper = client.post(
        f"/api/projects/{project.project_id}/collections/{collection_id}/items",
        json={
            "source_type": "paper",
            "source_id": str(collection_client["other_paper"].paper_id),
        },
    )
    assert invalid_paper.status_code == 404


def test_collections_are_shared_read_only_to_readers(collection_client):
    client = collection_client["client"]
    project = collection_client["project"]
    collection = _create_collection(client, str(project.project_id)).json()
    collection_id = collection["collection_id"]
    item = client.post(
        f"/api/projects/{project.project_id}/collections/{collection_id}/items",
        json={
            "source_type": "document",
            "source_id": str(collection_client["document"].document_id),
        },
    ).json()

    collection_client["active_user"]["user"] = collection_client["reader"]
    listed = client.get(f"/api/projects/{project.project_id}/collections")
    assert listed.status_code == 200
    assert listed.json()[0]["collection_id"] == collection_id
    assert len(listed.json()[0]["items"]) == 1

    create_denied = _create_collection(client, str(project.project_id), "Read next")
    assert create_denied.status_code == 403
    add_denied = client.post(
        f"/api/projects/{project.project_id}/collections/{collection_id}/items",
        json={
            "source_type": "paper",
            "source_id": str(collection_client["paper"].paper_id),
        },
    )
    assert add_denied.status_code == 403
    remove_denied = client.delete(
        f"/api/projects/{project.project_id}/collections/{collection_id}/items/{item['item_id']}"
    )
    assert remove_denied.status_code == 403
    rename_denied = client.patch(
        f"/api/projects/{project.project_id}/collections/{collection_id}",
        json={"name": "Updated"},
    )
    assert rename_denied.status_code == 403
    delete_denied = client.delete(
        f"/api/projects/{project.project_id}/collections/{collection_id}"
    )
    assert delete_denied.status_code == 403

    collection_client["active_user"]["user"] = collection_client["outsider"]
    hidden = client.get(f"/api/projects/{project.project_id}/collections")
    assert hidden.status_code == 404
