import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PythonWorkspace, PythonWorkspaceArtifact, ResearchProject, User
from app.schemas import (
    PythonArtifactMetadata,
    PythonWorkspaceFile,
    PythonWorkspaceResponse,
    PythonWorkspaceUpdate,
)
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.python_workspace import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    MAX_ARTIFACT_TOTAL_BYTES,
    validate_artifact,
    validate_artifact_name,
    validate_python_source_files,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/python",
    tags=["Python writing workspace"],
)

DEFAULT_PYTHON_CODE = """# CSV/TSV files selected for this run are available in /inputs.
# Save PNG, CSV, TSV, or TeX outputs under /outputs to use them in your draft.
import pandas as pd
import matplotlib.pyplot as plt

# Example:
# data = pd.read_csv("/inputs/study.csv")
"""


def _artifact_metadata(artifact: PythonWorkspaceArtifact) -> PythonArtifactMetadata:
    return PythonArtifactMetadata(
        filename=artifact.filename,
        content_type=artifact.content_type,
        byte_size=artifact.byte_size,
        updated_at=artifact.updated_at,
    )


def _workspace_response(
    workspace: PythonWorkspace | None,
    artifacts: list[PythonWorkspaceArtifact],
) -> PythonWorkspaceResponse:
    files = (
        workspace.files
        if workspace is not None and workspace.files
        else [{
            "filename": "main.py",
            "code": workspace.code if workspace else DEFAULT_PYTHON_CODE,
        }]
    )
    main_code = next(
        (source["code"] for source in files if source["filename"].casefold() == "main.py"),
        workspace.code if workspace else DEFAULT_PYTHON_CODE,
    )
    return PythonWorkspaceResponse(
        code=main_code,
        files=[PythonWorkspaceFile.model_validate(source) for source in files],
        updated_at=workspace.updated_at if workspace else None,
        artifacts=[_artifact_metadata(artifact) for artifact in artifacts],
    )


def _workspace(db: Session, project_id: uuid.UUID) -> PythonWorkspace | None:
    return db.get(PythonWorkspace, project_id)


def _artifacts(db: Session, project_id: uuid.UUID) -> list[PythonWorkspaceArtifact]:
    return list(
        db.scalars(
            select(PythonWorkspaceArtifact)
            .where(PythonWorkspaceArtifact.project_id == project_id)
            .order_by(PythonWorkspaceArtifact.filename)
        ).all()
    )


def _normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _updated_at_condition(db: Session, value: datetime):
    if db.get_bind().dialect.name == "sqlite":
        stored = func.replace(cast(PythonWorkspace.updated_at, String), ".000000", "")
        expected = func.replace(cast(value, String), ".000000", "")
        return stored == expected
    return PythonWorkspace.updated_at == value


@router.get("", response_model=PythonWorkspaceResponse)
def get_python_workspace(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    return _workspace_response(_workspace(db, project_id), _artifacts(db, project_id))


@router.put("", response_model=PythonWorkspaceResponse)
def save_python_workspace(
    project_id: uuid.UUID,
    payload: PythonWorkspaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    workspace = _workspace(db, project_id)
    if payload.files is not None:
        source_files = [source.model_dump() for source in payload.files]
    else:
        source_files = (
            [dict(source) for source in workspace.files]
            if workspace is not None and workspace.files
            else [{
                "filename": "main.py",
                "code": workspace.code if workspace else DEFAULT_PYTHON_CODE,
            }]
        )
        main_file = next(
            (source for source in source_files if source["filename"].casefold() == "main.py"),
            None,
        )
        if main_file is None:
            source_files.append({"filename": "main.py", "code": payload.code or ""})
        else:
            main_file["code"] = payload.code or ""
    try:
        source_files = validate_python_source_files(source_files)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    main_code = next(
        source["code"] for source in source_files if source["filename"].casefold() == "main.py"
    )
    if "expected_updated_at" in payload.model_fields_set:
        expected = _normalize_timestamp(payload.expected_updated_at)
        current = _normalize_timestamp(workspace.updated_at if workspace else None)
        if expected != current:
            raise HTTPException(
                status_code=409,
                detail="This Python workspace changed in another session. Reload the latest version before saving.",
            )
    if workspace is None:
        workspace = PythonWorkspace(
            project_id=project_id,
            code=main_code,
            files=source_files,
        )
        db.add(workspace)
    elif "expected_updated_at" in payload.model_fields_set:
        result = db.execute(
            update(PythonWorkspace)
            .where(
                PythonWorkspace.project_id == project_id,
                _updated_at_condition(db, workspace.updated_at),
            )
            .values(
                code=main_code,
                files=source_files,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This Python workspace changed in another session. Reload the latest version before saving.",
            )
    else:
        workspace.code = main_code
        workspace.files = source_files
        workspace.updated_at = datetime.now(timezone.utc)
    record_activity(db, user.user_id, "python_workspace.saved")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if "expected_updated_at" in payload.model_fields_set:
            raise HTTPException(
                status_code=409,
                detail="This Python workspace changed in another session. Reload the latest version before saving.",
            ) from None
        raise
    db.refresh(workspace)
    return _workspace_response(workspace, _artifacts(db, project_id))


@router.put("/artifacts", response_model=list[PythonArtifactMetadata])
async def save_python_artifacts(
    project_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > MAX_ARTIFACT_TOTAL_BYTES + 1024 * 1024:
            raise HTTPException(status_code=413, detail="Generated outputs exceed the 20 MB limit.")
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one generated output.")
    if len(files) > MAX_ARTIFACT_COUNT:
        raise HTTPException(
            status_code=413,
            detail=f"A project can store up to {MAX_ARTIFACT_COUNT} generated outputs.",
        )

    pending: list[tuple[str, str, bytes]] = []
    seen_names: set[str] = set()
    total_bytes = 0
    for file in files:
        filename = file.filename or ""
        try:
            content_type = validate_artifact_name(filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        folded_name = filename.casefold()
        if folded_name in seen_names:
            raise HTTPException(status_code=422, detail="Output filenames must be unique.")
        seen_names.add(folded_name)
        content = await file.read(MAX_ARTIFACT_BYTES + 1)
        if len(content) > MAX_ARTIFACT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{filename} exceeds the 5 MB per-file limit.",
            )
        total_bytes += len(content)
        if total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Generated outputs exceed the 20 MB limit.")
        try:
            content_type = validate_artifact(filename, content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        pending.append((filename, content_type, content))

    # Serialize project-wide quota checks across concurrent output batches.
    locked_project_id = db.scalar(
        select(ResearchProject.project_id)
        .where(ResearchProject.project_id == project_id)
        .with_for_update()
    )
    if locked_project_id is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    existing = _artifacts(db, project_id)
    existing_names = {artifact.filename.casefold() for artifact in existing}
    pending_names = {filename.casefold() for filename, _, _ in pending}
    new_names = pending_names - existing_names
    if len(existing) + len(new_names) > MAX_ARTIFACT_COUNT:
        raise HTTPException(
            status_code=413,
            detail=f"A project can store up to {MAX_ARTIFACT_COUNT} generated outputs.",
        )
    projected_total_bytes = sum(
        artifact.byte_size
        for artifact in existing
        if artifact.filename.casefold() not in pending_names
    ) + sum(len(content) for _, _, content in pending)
    if projected_total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Generated outputs exceed the {MAX_ARTIFACT_TOTAL_BYTES // (1024 * 1024)} MB project limit.",
        )

    by_name = {artifact.filename.casefold(): artifact for artifact in existing}
    for filename, content_type, content in pending:
        artifact = by_name.get(filename.casefold())
        if artifact is None:
            artifact = PythonWorkspaceArtifact(
                project_id=project_id,
                filename=filename,
                content_type=content_type,
                content=content,
                byte_size=len(content),
            )
            db.add(artifact)
            by_name[filename.casefold()] = artifact
        else:
            artifact.filename = filename
            artifact.content_type = content_type
            artifact.content = content
            artifact.byte_size = len(content)
            artifact.updated_at = datetime.now(timezone.utc)
    record_activity(db, user.user_id, "python_workspace.outputs_saved", {"count": len(pending)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Generated outputs changed in another session. Reload and run again.",
        ) from exc
    return [_artifact_metadata(artifact) for artifact in _artifacts(db, project_id)]


@router.get("/artifacts/{filename}")
def get_python_artifact(
    project_id: uuid.UUID,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    try:
        validate_artifact_name(filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    artifact = db.scalar(
        select(PythonWorkspaceArtifact).where(
            PythonWorkspaceArtifact.project_id == project_id,
            PythonWorkspaceArtifact.filename == filename,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Generated output not found.")
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{artifact.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/artifacts/{filename}", status_code=204)
def delete_python_artifact(
    project_id: uuid.UUID,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    try:
        validate_artifact_name(filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    artifact = db.scalar(
        select(PythonWorkspaceArtifact).where(
            PythonWorkspaceArtifact.project_id == project_id,
            PythonWorkspaceArtifact.filename == filename,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Generated output not found.")
    db.delete(artifact)
    record_activity(db, user.user_id, "python_workspace.output_deleted", {"filename": filename})
    db.commit()
    return Response(status_code=204)
