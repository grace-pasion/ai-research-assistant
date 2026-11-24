import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LatexWorkspace, ProjectInvitation, ResearchProject, TeamWorkspace, User, UserActivity
from app.routers import latex
from app.routers.latex import (
    DEFAULT_MAIN_TEX,
    compile_latex_workspace,
    get_latex_workspace,
    save_latex_workspace,
)
from app.schemas import LatexWorkspaceUpdate
from app.security import get_current_user


@pytest.fixture
def latex_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'latex.sqlite'}")
    for model in (User, TeamWorkspace, ResearchProject, ProjectInvitation, LatexWorkspace, UserActivity):
        model.__table__.create(engine)
    with Session(engine) as db:
        user = User(email="writer@example.com", name="Writer", password_hash="hashed")
        db.add(user)
        db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        db.add(project)
        db.commit()
        yield db, user, project
    engine.dispose()


def test_new_project_gets_latex_template_and_saved_files_persist(latex_database):
    db, user, project = latex_database

    initial = get_latex_workspace(project.project_id, db, user)
    assert initial.main_tex == DEFAULT_MAIN_TEX
    assert initial.references_bib == ""

    updated = LatexWorkspaceUpdate(
        main_tex=r"\section{Findings} \cite{smith2024}",
        references_bib="@article{smith2024, title={A study}}",
    )
    saved = save_latex_workspace(project.project_id, updated, db, user)
    assert saved.main_tex == updated.main_tex
    assert saved.references_bib == updated.references_bib

    with Session(db.get_bind()) as fresh_db:
        persisted = fresh_db.get(LatexWorkspace, project.project_id)
        assert persisted is not None
        assert persisted.main_tex == updated.main_tex
        assert persisted.references_bib == updated.references_bib
        loaded = get_latex_workspace(project.project_id, fresh_db, user)
        assert loaded.main_tex == updated.main_tex
        assert loaded.references_bib == updated.references_bib


def test_latex_workspace_is_private_to_the_project_owner(latex_database):
    db, _, project = latex_database
    other_user = User(
        user_id=uuid.uuid4(),
        email="other@example.com",
        name="Other",
        password_hash="hashed",
    )

    with pytest.raises(HTTPException) as error:
        get_latex_workspace(project.project_id, db, other_user)
    assert error.value.status_code == 404


def test_stale_collaborative_workspace_save_is_rejected(latex_database):
    db, owner, project = latex_database
    initially_loaded = get_latex_workspace(project.project_id, db, owner)
    collaborator = User(
        email="collaborator@example.com",
        username="collaborator",
        name="Collaborator",
        password_hash="hashed",
    )
    db.add(collaborator)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=collaborator.user_id,
            status="accepted",
        )
    )
    db.commit()
    saved = save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex="First edit",
            references_bib="",
            expected_updated_at=initially_loaded.updated_at,
        ),
        db,
        owner,
    )
    assert saved.updated_at is not None
    assert get_latex_workspace(project.project_id, db, collaborator).main_tex == "First edit"

    with pytest.raises(HTTPException) as stale:
        save_latex_workspace(
            project.project_id,
            LatexWorkspaceUpdate(
                main_tex="Outdated edit",
                references_bib="",
                expected_updated_at=initially_loaded.updated_at,
            ),
            db,
            owner,
        )
    assert stale.value.status_code == 409
    assert get_latex_workspace(project.project_id, db, owner).main_tex == "First edit"


def test_latex_workspace_rejects_oversized_source():
    with pytest.raises(ValidationError):
        LatexWorkspaceUpdate(main_tex="x" * 1_000_001, references_bib="")
    with pytest.raises(ValidationError):
        LatexWorkspaceUpdate(main_tex="", references_bib="x" * 500_001)


def test_compile_returns_pdf_for_readers_and_checks_project_access(latex_database, monkeypatch):
    db, owner, project = latex_database
    reader = User(
        email="reader@example.com",
        name="Reader",
        password_hash="hashed",
    )
    db.add(reader)
    db.flush()
    db.add(
        ProjectInvitation(
            project_id=project.project_id,
            inviter_id=owner.user_id,
            invitee_id=reader.user_id,
            status="accepted",
            role="read",
        )
    )
    db.commit()
    monkeypatch.setattr(latex, "compile_latex", lambda _main, _bib: b"%PDF-1.7 test")

    response = compile_latex_workspace(project.project_id, db, reader)
    assert response.media_type == "application/pdf"
    assert response.body.startswith(b"%PDF-")

    outsider = User(
        user_id=uuid.uuid4(),
        email="outsider@example.com",
        name="Outsider",
        password_hash="hashed",
    )
    with pytest.raises(HTTPException) as error:
        compile_latex_workspace(project.project_id, db, outsider)
    assert error.value.status_code == 404


def test_compile_rejects_citation_keys_missing_from_bibliography(latex_database):
    db, owner, project = latex_database
    save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex=r"\begin{document}\cite{missing2024}\end{document}",
            references_bib="",
        ),
        db,
        owner,
    )

    with pytest.raises(HTTPException) as error:
        compile_latex_workspace(project.project_id, db, owner)
    assert error.value.status_code == 422
    assert "missing2024" in error.value.detail


def test_compile_http_route_returns_pdf_bytes(latex_database, monkeypatch):
    db, owner, project = latex_database
    api = FastAPI()
    api.include_router(latex.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: owner
    monkeypatch.setattr(latex, "compile_latex", lambda _main, _bib: b"%PDF-1.7 route test")

    with TestClient(api) as client:
        response = client.post(f"/api/projects/{project.project_id}/latex/compile")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
