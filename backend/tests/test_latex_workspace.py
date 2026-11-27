import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    LatexWorkspace,
    ProjectActivity,
    ProjectInvitation,
    ProjectFileVersion,
    PythonAnalysisRun,
    PythonWorkspaceArtifact,
    ResearchProject,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import latex
from app.routers.latex import (
    DEFAULT_MAIN_TEX,
    compile_latex_workspace,
    get_latex_workspace,
    get_latex_workspace_history,
    get_latex_workspace_version,
    restore_latex_workspace_version,
    save_latex_workspace,
)
from app.schemas import LatexWorkspaceUpdate, WorkspaceRestoreRequest
from app.security import get_current_user


@pytest.fixture
def latex_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'latex.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        LatexWorkspace,
        ProjectFileVersion,
        PythonAnalysisRun,
        PythonWorkspaceArtifact,
        UserActivity,
        ProjectActivity,
    ):
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


def test_latex_history_deduplicates_saves_and_restore_creates_a_new_version(latex_database):
    db, owner, project = latex_database
    initial = get_latex_workspace(project.project_id, db, owner)
    first = save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex="First draft",
            references_bib="@article{first, title={First}}",
            expected_updated_at=initial.updated_at,
        ),
        db,
        owner,
    )
    saved = save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex="Second draft",
            references_bib="@article{first, title={First}}",
            expected_updated_at=first.updated_at,
        ),
        db,
        owner,
    )

    history = get_latex_workspace_history(project.project_id, db, owner)
    main_versions = [version for version in history if version.filename == "main.tex"]
    assert [version.version_number for version in main_versions] == [3, 2, 1]
    reference_versions = [
        version for version in history if version.filename == "references.bib"
    ]
    assert [version.version_number for version in reference_versions] == [2, 1]

    restored = restore_latex_workspace_version(
        project.project_id,
        main_versions[-1].version_id,
        WorkspaceRestoreRequest(expected_updated_at=saved.updated_at),
        db,
        owner,
    )
    assert restored.main_tex == DEFAULT_MAIN_TEX
    assert restored.references_bib == "@article{first, title={First}}"
    restored_history = [
        version for version in get_latex_workspace_history(project.project_id, db, owner)
        if version.filename == "main.tex"
    ]
    assert [version.version_number for version in restored_history] == [4, 3, 2, 1]

    with pytest.raises(HTTPException) as stale:
        restore_latex_workspace_version(
            project.project_id,
            main_versions[0].version_id,
            WorkspaceRestoreRequest(expected_updated_at=saved.updated_at),
            db,
            owner,
        )
    assert stale.value.status_code == 409


def test_latex_history_comparison_returns_content_and_rejects_other_workspace_versions(
    latex_database,
):
    db, owner, project = latex_database
    workspace = get_latex_workspace(project.project_id, db, owner)
    first = save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex="Earlier draft",
            references_bib="",
            expected_updated_at=workspace.updated_at,
        ),
        db,
        owner,
    )
    saved = save_latex_workspace(
        project.project_id,
        LatexWorkspaceUpdate(
            main_tex="Current draft",
            references_bib="",
            expected_updated_at=first.updated_at,
        ),
        db,
        owner,
    )
    version = next(
        version for version in get_latex_workspace_history(project.project_id, db, owner)
        if version.filename == "main.tex" and version.version_number == 2
    )
    python_version = ProjectFileVersion(
        project_id=project.project_id,
        workspace_type="python",
        filename="main.py",
        version_number=1,
        content="print('not a LaTeX version')",
        created_by=owner.user_id,
        created_at=version.created_at,
    )
    db.add(python_version)
    db.commit()

    api = FastAPI()
    api.include_router(latex.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(api) as client:
        detail = client.get(
            f"/api/projects/{project.project_id}/latex/history/{version.version_id}"
        )
        wrong_workspace = client.get(
            f"/api/projects/{project.project_id}/latex/history/{python_version.version_id}"
        )

    assert detail.status_code == 200
    assert detail.json()["content"] == "Earlier draft"
    assert detail.json()["author_name"] == owner.name
    assert wrong_workspace.status_code == 404
    assert saved.main_tex == "Current draft"


def test_latex_history_retains_only_the_latest_twenty_versions(latex_database):
    db, owner, project = latex_database
    workspace = get_latex_workspace(project.project_id, db, owner)
    for index in range(24):
        workspace = save_latex_workspace(
            project.project_id,
            LatexWorkspaceUpdate(
                main_tex=f"Draft {index}",
                references_bib="",
                expected_updated_at=workspace.updated_at,
            ),
            db,
            owner,
        )
    versions = [
        version for version in get_latex_workspace_history(project.project_id, db, owner)
        if version.filename == "main.tex"
    ]
    assert len(versions) == 20
    assert versions[0].version_number == 25
    assert versions[-1].version_number == 6


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
    monkeypatch.setattr(latex, "compile_latex", lambda _main, _bib, _assets: b"%PDF-1.7 test")

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
    monkeypatch.setattr(
        latex,
        "compile_latex",
        lambda _main, _bib, _assets: b"%PDF-1.7 route test",
    )

    with TestClient(api) as client:
        response = client.post(f"/api/projects/{project.project_id}/latex/compile")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
