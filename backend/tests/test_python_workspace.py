import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import ensure_python_workspace_files_column, get_db
from app.models import (
    LatexWorkspace,
    ProjectInvitation,
    PythonWorkspace,
    PythonWorkspaceArtifact,
    ResearchProject,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers import latex
from app.routers import python_workspace
from app.routers.python_workspace import DEFAULT_PYTHON_CODE
from app.schemas import PythonWorkspaceUpdate
from app.security import get_current_user

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2cAAAAASUVORK5CYII="
)


def test_python_workspace_files_migration_preserves_existing_code(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-python-workspace.sqlite'}")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE python_workspaces (project_id CHAR(32) PRIMARY KEY, "
                "code TEXT NOT NULL, updated_at DATETIME)"
            ))
            connection.execute(text(
                "INSERT INTO python_workspaces (project_id, code) VALUES ('project-1', 'print(1)')"
            ))

        ensure_python_workspace_files_column(engine)
        ensure_python_workspace_files_column(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("python_workspaces")}
        with engine.connect() as connection:
            code = connection.execute(
                text("SELECT code FROM python_workspaces WHERE project_id = 'project-1'")
            ).scalar_one()
        assert "files" in columns
        assert code == "print(1)"
    finally:
        engine.dispose()


def _client(db, user):
    api = FastAPI()
    api.include_router(python_workspace.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _upload(filename, content=PNG_BYTES):
    return {"files": (filename, content, "application/octet-stream")}


def _database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'python-workspace.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        UserActivity,
        LatexWorkspace,
        PythonWorkspace,
        PythonWorkspaceArtifact,
    ):
        model.__table__.create(engine)
    db = Session(engine)
    owner = User(email="writer@example.com", name="Writer", password_hash="hashed")
    db.add(owner)
    db.flush()
    project = ResearchProject(user_id=owner.user_id, project_name="Analysis")
    db.add(project)
    db.commit()
    return engine, db, owner, project


def test_python_workspace_persists_code_and_rejects_stale_saves(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    try:
        with _client(db, owner) as client:
            path = f"/api/projects/{project.project_id}/python"
            initial = client.get(path).json()
            assert initial["code"] == DEFAULT_PYTHON_CODE
            assert initial["updated_at"] is None

            first = client.put(
                path,
                json={"code": "print('first')", "expected_updated_at": None},
            )
            assert first.status_code == 200
            saved = first.json()
            assert saved["code"] == "print('first')"
            assert saved["updated_at"] is not None

            stale = client.put(
                path,
                json={"code": "print('stale')", "expected_updated_at": None},
            )
            assert stale.status_code == 409
            assert client.get(path).json()["code"] == "print('first')"
    finally:
        db.close()
        engine.dispose()


def test_python_workspace_persists_multiple_files_and_keeps_legacy_code_updates(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python"
    try:
        with _client(db, owner) as client:
            response = client.put(
                path,
                json={
                    "files": [
                        {"filename": "main.py", "code": "from helpers import total\nprint(total())"},
                        {"filename": "helpers.py", "code": "def total(): return 42"},
                    ],
                    "expected_updated_at": None,
                },
            )
            assert response.status_code == 200
            saved = response.json()
            assert saved["code"] == "from helpers import total\nprint(total())"
            assert saved["files"] == [
                {"filename": "main.py", "code": "from helpers import total\nprint(total())"},
                {"filename": "helpers.py", "code": "def total(): return 42"},
            ]

            legacy_update = client.put(
                path,
                json={"code": "print('legacy client')", "expected_updated_at": saved["updated_at"]},
            )
            assert legacy_update.status_code == 200
            assert legacy_update.json()["code"] == "print('legacy client')"
            assert legacy_update.json()["files"][1] == {
                "filename": "helpers.py",
                "code": "def total(): return 42",
            }
            stale = client.put(
                path,
                json={
                    "files": [
                        {"filename": "main.py", "code": "print('stale')"},
                        {"filename": "helpers.py", "code": "def total(): return 0"},
                    ],
                    "expected_updated_at": saved["updated_at"],
                },
            )
            assert stale.status_code == 409
            latest = client.get(path).json()
            assert latest["code"] == "print('legacy client')"
            assert latest["files"][1]["code"] == "def total(): return 42"
    finally:
        db.close()
        engine.dispose()


def test_python_workspace_rejects_unsafe_or_incomplete_file_sets(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python"
    invalid_sets = [
        [{"filename": "../main.py", "code": ""}],
        [{"filename": "MAIN.PY", "code": ""}],
        [
            {"filename": "main.py", "code": ""},
            {"filename": "MAIN.PY", "code": ""},
        ],
        [{"filename": "helpers.py", "code": ""}],
    ]
    try:
        with _client(db, owner) as client:
            for files in invalid_sets:
                response = client.put(path, json={"files": files})
                assert response.status_code == 422
            assert client.get(path).json()["files"] == [
                {"filename": "main.py", "code": DEFAULT_PYTHON_CODE},
            ]
    finally:
        db.close()
        engine.dispose()


def test_python_workspace_enforces_source_file_and_total_limits(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python"
    too_many_files = [
        {"filename": f"module{index}.py", "code": ""}
        for index in range(20)
    ]
    too_many_files[0]["filename"] = "main.py"
    oversized_total = [
        {"filename": "main.py", "code": "x" * 90_000},
        {"filename": "helper.py", "code": "y" * 90_000},
        {"filename": "other.py", "code": "z" * 90_000},
        {"filename": "extra.py", "code": "w" * 90_000},
        {"filename": "last.py", "code": "v" * 90_000},
        {"filename": "sixth.py", "code": "u" * 90_000},
    ]
    try:
        with _client(db, owner) as client:
            assert client.put(
                path,
                json={"files": too_many_files + [{"filename": "extra.py", "code": ""}]},
            ).status_code == 422
            assert client.put(path, json={"files": oversized_total}).status_code == 422
            assert client.get(path).json()["files"] == [
                {"filename": "main.py", "code": DEFAULT_PYTHON_CODE},
            ]
    finally:
        db.close()
        engine.dispose()


def test_readers_can_view_but_not_edit_python_workspace_or_outputs(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    reader = User(email="reader@example.com", name="Reader", password_hash="hashed")
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
    try:
        with _client(db, reader) as client:
            path = f"/api/projects/{project.project_id}/python"
            assert client.get(path).status_code == 200
            assert client.put(path, json={"code": "print(1)"}).status_code == 403
            assert client.put(
                f"{path}/artifacts",
                files=[("files", _upload("figure.png")["files"])],
            ).status_code == 403
    finally:
        db.close()
        engine.dispose()


def test_artifacts_are_validated_persisted_replaceable_and_deletable(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python"
    try:
        with _client(db, owner) as client:
            upload = client.put(
                f"{path}/artifacts",
                files=[("files", _upload("figure.png")["files"])],
            )
            assert upload.status_code == 200
            assert upload.json()[0]["filename"] == "figure.png"
            assert upload.json()[0]["content_type"] == "image/png"

            download = client.get(f"{path}/artifacts/figure.png")
            assert download.status_code == 200
            assert download.content == PNG_BYTES
            assert download.headers["content-type"] == "image/png"

            replaced_bytes = PNG_BYTES + b"\x00"
            replaced = client.put(
                f"{path}/artifacts",
                files=[("files", _upload("figure.png", replaced_bytes)["files"])],
            )
            assert replaced.status_code == 200
            assert client.get(f"{path}/artifacts/figure.png").content == replaced_bytes

            assert client.delete(f"{path}/artifacts/figure.png").status_code == 204
            assert client.get(f"{path}/artifacts/figure.png").status_code == 404
    finally:
        db.close()
        engine.dispose()


def test_artifact_upload_rejects_unsafe_names_types_and_contents_atomically(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python/artifacts"
    try:
        with _client(db, owner) as client:
            unsafe = client.put(path, files=[("files", _upload("../figure.png")["files"])])
            unsupported = client.put(path, files=[("files", _upload("figure.svg")["files"])])
            invalid_png = client.put(path, files=[("files", ("figure.png", b"not png", "image/png"))])
            invalid_utf8 = client.put(path, files=[("files", ("table.tex", b"\xff", "text/plain"))])
            oversized = client.put(
                path,
                files=[("files", ("large.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv"))],
            )

            assert unsafe.status_code == 422
            assert unsupported.status_code == 422
            assert invalid_png.status_code == 422
            assert invalid_utf8.status_code == 422
            assert oversized.status_code == 413
            assert client.get(f"/api/projects/{project.project_id}/python").json()["artifacts"] == []
    finally:
        db.close()
        engine.dispose()


def test_artifact_count_limit_does_not_partially_save_a_batch(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    path = f"/api/projects/{project.project_id}/python/artifacts"
    try:
        with _client(db, owner) as client:
            batch = [
                ("files", _upload(f"figure-{index}.png")["files"])
                for index in range(20)
            ]
            assert client.put(path, files=batch).status_code == 200
            overflow = client.put(
                path,
                files=[
                    ("files", _upload("new.png")["files"]),
                    ("files", _upload("also-new.png")["files"]),
                ],
            )
            assert overflow.status_code == 413
            stored = client.get(f"/api/projects/{project.project_id}/python").json()["artifacts"]
            assert len(stored) == 20
    finally:
        db.close()
        engine.dispose()


def test_artifact_total_limit_applies_across_runs_and_allows_replacements(tmp_path, monkeypatch):
    engine, db, owner, project = _database(tmp_path)
    monkeypatch.setattr(python_workspace, "MAX_ARTIFACT_TOTAL_BYTES", 10)
    db.add(
        PythonWorkspaceArtifact(
            project_id=project.project_id,
            filename="table.csv",
            content_type="text/csv",
            content=b"123456789",
            byte_size=9,
        )
    )
    db.commit()
    path = f"/api/projects/{project.project_id}/python/artifacts"
    try:
        with _client(db, owner) as client:
            replacement = client.put(
                path,
                files=[("files", ("table.csv", b"1234567890", "text/csv"))],
            )
            assert replacement.status_code == 200

            overflow = client.put(
                path,
                files=[("files", ("extra.csv", b"x", "text/csv"))],
            )
            assert overflow.status_code == 413
            artifacts = client.get(
                f"/api/projects/{project.project_id}/python"
            ).json()["artifacts"]
            assert [(artifact["filename"], artifact["byte_size"]) for artifact in artifacts] == [
                ("table.csv", 10),
            ]
    finally:
        db.close()
        engine.dispose()


def test_python_workspace_rejects_oversized_source():
    with pytest.raises(ValidationError):
        PythonWorkspaceUpdate(code="x" * 100_001)


def test_python_workspace_rejects_source_whose_utf8_size_exceeds_limit(tmp_path):
    engine, db, owner, project = _database(tmp_path)
    try:
        with _client(db, owner) as client:
            response = client.put(
                f"/api/projects/{project.project_id}/python",
                json={"code": "é" * 60_000},
            )
        assert response.status_code == 422
        assert db.get(PythonWorkspace, project.project_id) is None
    finally:
        db.close()
        engine.dispose()


def test_pdf_compilation_receives_saved_python_outputs(tmp_path, monkeypatch):
    engine, db, owner, project = _database(tmp_path)
    artifact = PythonWorkspaceArtifact(
        project_id=project.project_id,
        filename="figure.png",
        content_type="image/png",
        content=PNG_BYTES,
        byte_size=len(PNG_BYTES),
    )
    db.add(artifact)
    db.commit()
    received_assets = {}
    monkeypatch.setattr(
        latex,
        "compile_latex",
        lambda _main, _bib, assets: received_assets.update(assets) or b"%PDF-1.7 test",
    )
    try:
        response = latex.compile_latex_workspace(project.project_id, db, owner)
        assert response.body == b"%PDF-1.7 test"
        assert received_assets == {"figure.png": PNG_BYTES}
    finally:
        db.close()
        engine.dispose()
