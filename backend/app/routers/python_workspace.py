import base64
import binascii
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    ProjectFileVersion,
    PythonAnalysisRun,
    PythonWorkspace,
    PythonWorkspaceArtifact,
    ResearchProject,
    User,
)
from app.schemas import (
    PythonArtifactMetadata,
    PythonWorkspaceFile,
    PythonWorkspaceResponse,
    PythonWorkspaceUpdate,
    PythonRunInputMetadata,
    PythonRunProvenance,
    WorkspaceRestoreRequest,
    WorkspaceVersionDetails,
    WorkspaceVersionMetadata,
)
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.python_workspace import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    MAX_ARTIFACT_TOTAL_BYTES,
    INPUT_FILENAME_PATTERN,
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILE_COUNT,
    MAX_INPUT_TOTAL_BYTES,
    MAX_RUN_SNAPSHOT_TOTAL_BYTES,
    validate_artifact,
    validate_artifact_name,
    validate_python_source_files,
)
from app.services.workspace_history import (
    get_file_version,
    list_file_versions,
    record_file_version,
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
        script_filename=artifact.script_filename,
        input_filenames=artifact.input_filenames,
        run_id=artifact.run_id,
        run_at=_normalize_timestamp(artifact.run_at),
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


def _delete_unreferenced_runs(db: Session, project_id: uuid.UUID) -> None:
    referenced_ids = set(
        db.scalars(
            select(PythonWorkspaceArtifact.run_id).where(
                PythonWorkspaceArtifact.project_id == project_id,
                PythonWorkspaceArtifact.run_id.is_not(None),
            )
        ).all()
    )
    runs = db.scalars(
        select(PythonAnalysisRun).where(PythonAnalysisRun.project_id == project_id)
    ).all()
    for run in runs:
        if run.run_id not in referenced_ids:
            db.delete(run)


def _run_snapshot_size(run: PythonAnalysisRun) -> int:
    source_bytes = sum(len(source["code"].encode("utf-8")) for source in run.source_files)
    input_bytes = sum(int(input_file["byte_size"]) for input_file in run.input_files)
    return source_bytes + input_bytes


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


@router.get("/history", response_model=list[WorkspaceVersionMetadata])
def get_python_workspace_history(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    return [
        WorkspaceVersionMetadata(
            version_id=version.version_id,
            filename=version.filename,
            version_number=version.version_number,
            created_at=version.created_at,
            author_name=author_name,
        )
        for version, author_name in list_file_versions(db, project_id, "python")
    ]


@router.get("/history/{version_id}", response_model=WorkspaceVersionDetails)
def get_python_workspace_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    result = get_file_version(db, project_id, "python", version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Python file version not found.")
    version, author_name = result
    return WorkspaceVersionDetails(
        version_id=version.version_id,
        filename=version.filename,
        version_number=version.version_number,
        created_at=version.created_at,
        author_name=author_name,
        content=version.content,
    )


@router.post("/history/{version_id}/restore", response_model=PythonWorkspaceResponse)
def restore_python_workspace_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: WorkspaceRestoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    workspace = _workspace(db, project_id)
    expected = _normalize_timestamp(payload.expected_updated_at)
    current_updated_at = _normalize_timestamp(workspace.updated_at if workspace else None)
    if expected != current_updated_at:
        raise HTTPException(
            status_code=409,
            detail="This Python workspace changed in another session. Reload the latest version before restoring.",
        )

    version = db.get(ProjectFileVersion, version_id)
    if (
        version is None
        or version.project_id != project_id
        or version.workspace_type != "python"
    ):
        raise HTTPException(status_code=404, detail="Python file version not found.")

    source_files = (
        [dict(source) for source in workspace.files]
        if workspace is not None and workspace.files
        else [{
            "filename": "main.py",
            "code": workspace.code if workspace else DEFAULT_PYTHON_CODE,
        }]
    )
    existing_file = next(
        (source for source in source_files if source["filename"] == version.filename),
        None,
    )
    current_content = existing_file["code"] if existing_file else None
    if current_content == version.content:
        return _workspace_response(workspace, _artifacts(db, project_id))

    if existing_file is None:
        source_files.append({"filename": version.filename, "code": version.content})
    else:
        existing_file["code"] = version.content
    try:
        source_files = validate_python_source_files(source_files)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    main_code = next(
        source["code"] for source in source_files if source["filename"] == "main.py"
    )
    if workspace is None:
        workspace = PythonWorkspace(
            project_id=project_id,
            code=main_code,
            files=source_files,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(workspace)
    else:
        now = datetime.now(timezone.utc)
        result = db.execute(
            update(PythonWorkspace)
            .where(
                PythonWorkspace.project_id == project_id,
                _updated_at_condition(db, workspace.updated_at),
            )
            .values(code=main_code, files=source_files, updated_at=now)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This Python workspace changed in another session. Reload the latest version before restoring.",
            )
        workspace.updated_at = now
    try:
        if current_content is not None:
            record_file_version(
                db,
                project_id,
                "python",
                version.filename,
                current_content,
                user.user_id,
            )
        record_file_version(
            db,
            project_id,
            "python",
            version.filename,
            version.content,
            user.user_id,
            force=True,
        )
        record_activity(
            db,
            user.user_id,
            "python_workspace.version_restored",
            {"filename": version.filename, "version_number": version.version_number},
            project_id=project_id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This Python workspace changed in another session. Reload the latest version before restoring.",
        ) from None
    db.refresh(workspace)
    return _workspace_response(workspace, _artifacts(db, project_id))


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
    old_files = (
        [dict(source) for source in workspace.files]
        if workspace is not None and workspace.files
        else [{
            "filename": "main.py",
            "code": workspace.code if workspace else DEFAULT_PYTHON_CODE,
        }]
    )
    new_by_filename = {source["filename"]: source["code"] for source in source_files}
    old_by_filename = {source["filename"]: source["code"] for source in old_files}
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
    try:
        db.flush()
        for filename in old_by_filename.keys() | new_by_filename.keys():
            if filename in old_by_filename:
                record_file_version(
                    db,
                    project_id,
                    "python",
                    filename,
                    old_by_filename[filename],
                    None,
                )
            if filename in new_by_filename:
                record_file_version(
                    db,
                    project_id,
                    "python",
                    filename,
                    new_by_filename[filename],
                    user.user_id,
                )
        record_activity(db, user.user_id, "python_workspace.saved", project_id=project_id)
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
    script_filename: str | None = Form(default=None),
    input_filenames: str | None = Form(default=None),
    source_files: str | None = Form(default=None),
    run_at: datetime | None = Form(default=None),
    inputs: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    try:
        parsed_input_filenames = json.loads(input_filenames or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Input filenames must be valid JSON.") from exc
    if (
        not isinstance(parsed_input_filenames, list)
        or len(parsed_input_filenames) > MAX_INPUT_FILE_COUNT
        or any(
            not isinstance(filename, str)
            or not INPUT_FILENAME_PATTERN.fullmatch(filename)
            or not filename.casefold().endswith((".csv", ".tsv"))
            for filename in parsed_input_filenames
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Input provenance must contain up to {MAX_INPUT_FILE_COUNT} simple CSV/TSV filenames.",
        )
    folded_inputs = [filename.casefold() for filename in parsed_input_filenames]
    if len(set(folded_inputs)) != len(folded_inputs):
        raise HTTPException(status_code=422, detail="Input filenames must be unique.")

    parsed_source_files = None
    if source_files is not None:
        try:
            decoded_source_files = json.loads(source_files)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Source snapshot must be valid JSON.") from exc
        if (
            not isinstance(decoded_source_files, list)
            or any(
                not isinstance(source, dict)
                or not isinstance(source.get("filename"), str)
                or not isinstance(source.get("code"), str)
                for source in decoded_source_files
            )
        ):
            raise HTTPException(status_code=422, detail="Source snapshot must contain Python files.")
        try:
            parsed_source_files = validate_python_source_files(decoded_source_files)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    has_run_snapshot = source_files is not None or run_at is not None or bool(inputs)
    parsed_run_inputs: list[dict[str, str | int]] = []
    if has_run_snapshot:
        if parsed_source_files is None or run_at is None or script_filename is None:
            raise HTTPException(
                status_code=422,
                detail="A reproducible run requires its source snapshot, script filename, and run time.",
            )
        if run_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="Run time must include a timezone.")
        if not any(source["filename"] == script_filename for source in parsed_source_files):
            raise HTTPException(
                status_code=422,
                detail="The run script must be included in the source snapshot.",
            )
        if len(inputs) > MAX_INPUT_FILE_COUNT:
            raise HTTPException(
                status_code=413,
                detail=f"A run can include up to {MAX_INPUT_FILE_COUNT} input files.",
            )
        total_input_bytes = 0
        seen_input_names: set[str] = set()
        for input_file in inputs:
            filename = input_file.filename or ""
            if (
                not INPUT_FILENAME_PATTERN.fullmatch(filename)
                or not filename.casefold().endswith((".csv", ".tsv"))
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Input files must have simple CSV or TSV filenames.",
                )
            folded_name = filename.casefold()
            if folded_name in seen_input_names:
                raise HTTPException(status_code=422, detail="Input filenames must be unique.")
            seen_input_names.add(folded_name)
            content = await input_file.read(MAX_INPUT_FILE_BYTES + 1)
            if not content:
                raise HTTPException(status_code=422, detail=f"{filename} is empty.")
            if len(content) > MAX_INPUT_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"{filename} exceeds the 5 MB input-file limit.",
                )
            total_input_bytes += len(content)
            if total_input_bytes > MAX_INPUT_TOTAL_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Input files exceed the 20 MB per-run limit.",
                )
            parsed_run_inputs.append({
                "filename": filename,
                "byte_size": len(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
            })
        actual_input_names = [str(input_file["filename"]) for input_file in parsed_run_inputs]
        if input_filenames is not None and [name.casefold() for name in actual_input_names] != folded_inputs:
            raise HTTPException(
                status_code=422,
                detail="Input filenames must match the uploaded input-file snapshots.",
            )
        parsed_input_filenames = actual_input_names

    if script_filename is not None:
        source_files = _workspace_response(_workspace(db, project_id), []).files
        if not any(source.filename == script_filename for source in source_files):
            raise HTTPException(
                status_code=422,
                detail="The run script must be a saved file in this Python workspace.",
            )
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        maximum_request_bytes = (
            MAX_ARTIFACT_TOTAL_BYTES + MAX_INPUT_TOTAL_BYTES + 8 * 1024 * 1024
        )
        if int(content_length) > maximum_request_bytes:
            raise HTTPException(
                status_code=413,
                detail="Generated outputs and input snapshots exceed the request-size limit.",
            )
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

    run = None
    normalized_run_at = run_at.astimezone(timezone.utc) if has_run_snapshot and run_at else None
    if has_run_snapshot:
        retained_run_ids = {
            artifact.run_id
            for artifact in existing
            if artifact.run_id is not None
            and artifact.filename.casefold() not in pending_names
        }
        retained_runs = (
            db.scalars(
                select(PythonAnalysisRun).where(
                    PythonAnalysisRun.project_id == project_id,
                    PythonAnalysisRun.run_id.in_(retained_run_ids),
                )
            ).all()
            if retained_run_ids
            else []
        )
        new_run_size = sum(
            len(source["code"].encode("utf-8")) for source in parsed_source_files or []
        ) + sum(int(input_file["byte_size"]) for input_file in parsed_run_inputs)
        retained_snapshot_bytes = sum(_run_snapshot_size(existing_run) for existing_run in retained_runs)
        if retained_snapshot_bytes + new_run_size > MAX_RUN_SNAPSHOT_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Saved Python run snapshots exceed the 100 MB per-project limit.",
            )
        run = PythonAnalysisRun(
            project_id=project_id,
            script_filename=script_filename,
            source_files=parsed_source_files,
            input_files=parsed_run_inputs,
            run_at=normalized_run_at,
            created_by=user.user_id,
        )
        db.add(run)
        db.flush()

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
                script_filename=script_filename,
                input_filenames=parsed_input_filenames,
                run_id=run.run_id if run else None,
                run_at=normalized_run_at,
            )
            db.add(artifact)
            by_name[filename.casefold()] = artifact
        else:
            artifact.filename = filename
            artifact.content_type = content_type
            artifact.content = content
            artifact.byte_size = len(content)
            artifact.script_filename = script_filename
            artifact.input_filenames = parsed_input_filenames
            artifact.run_id = run.run_id if run else None
            artifact.run_at = normalized_run_at
            artifact.updated_at = datetime.now(timezone.utc)
    record_activity(
        db,
        user.user_id,
        "python_workspace.outputs_saved",
        {"count": len(pending)},
        project_id=project_id,
    )
    try:
        db.flush()
        _delete_unreferenced_runs(db, project_id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Generated outputs changed in another session. Reload and run again.",
        ) from exc
    return [_artifact_metadata(artifact) for artifact in _artifacts(db, project_id)]


@router.get("/runs/{run_id}", response_model=PythonRunProvenance)
def get_python_run_provenance(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    run = db.scalar(
        select(PythonAnalysisRun).where(
            PythonAnalysisRun.project_id == project_id,
            PythonAnalysisRun.run_id == run_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Python run provenance not found.")
    return PythonRunProvenance(
        run_id=run.run_id,
        run_at=_normalize_timestamp(run.run_at),
        script_filename=run.script_filename,
        source_files=run.source_files,
        inputs=[
            PythonRunInputMetadata(filename=str(item["filename"]), byte_size=int(item["byte_size"]))
            for item in run.input_files
        ],
    )


@router.get("/runs/{run_id}/inputs/{filename}")
def download_python_run_input(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    if not INPUT_FILENAME_PATTERN.fullmatch(filename):
        raise HTTPException(status_code=422, detail="Input filename is invalid.")
    run = db.scalar(
        select(PythonAnalysisRun).where(
            PythonAnalysisRun.project_id == project_id,
            PythonAnalysisRun.run_id == run_id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Python run provenance not found.")
    input_file = next(
        (item for item in run.input_files if item["filename"] == filename),
        None,
    )
    if input_file is None:
        raise HTTPException(status_code=404, detail="Run input file not found.")
    try:
        content = base64.b64decode(str(input_file["content_base64"]), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Stored run input is invalid.") from exc
    content_type = "text/csv" if filename.casefold().endswith(".csv") else "text/tab-separated-values"
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


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
    record_activity(
        db,
        user.user_id,
        "python_workspace.output_deleted",
        {"filename": filename},
        project_id=project_id,
    )
    db.flush()
    _delete_unreferenced_runs(db, project_id)
    db.commit()
    return Response(status_code=204)
