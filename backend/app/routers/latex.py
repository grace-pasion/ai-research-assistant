import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LatexWorkspace, ProjectFileVersion, PythonWorkspaceArtifact, User
from app.schemas import (
    LatexWorkspaceResponse,
    LatexWorkspaceUpdate,
    WorkspaceRestoreRequest,
    WorkspaceVersionMetadata,
)
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.latex_compiler import (
    LatexCompilationError,
    LatexCompilerUnavailable,
    compile_latex,
)
from app.services.workspace_history import list_file_versions, record_file_version

router = APIRouter(prefix="/api/projects/{project_id}/latex", tags=["LaTeX workspace"])

DEFAULT_MAIN_TEX = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{natbib}

\title{Untitled Research Article}
\author{}
\date{\today}

\begin{document}
\maketitle

\begin{abstract}
Add a short summary of your research here.
\end{abstract}

\section{Introduction}
Start drafting your research here. Select a saved paper to insert a citation, or import an excerpt from a project document.

\bibliographystyle{plainnat}
\bibliography{references}
\end{document}
"""


def _get_workspace(db: Session, project_id: uuid.UUID) -> LatexWorkspace | None:
    return db.scalar(
        select(LatexWorkspace).where(LatexWorkspace.project_id == project_id)
    )


def _updated_at_condition(db: Session, value: datetime):
    if db.get_bind().dialect.name == "sqlite":
        stored = func.replace(cast(LatexWorkspace.updated_at, String), ".000000", "")
        expected = func.replace(cast(value, String), ".000000", "")
        return stored == expected
    return LatexWorkspace.updated_at == value


@router.get("", response_model=LatexWorkspaceResponse)
def get_latex_workspace(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    workspace = _get_workspace(db, project_id)
    if workspace is None:
        return LatexWorkspaceResponse(main_tex=DEFAULT_MAIN_TEX, references_bib="", updated_at=None)
    return LatexWorkspaceResponse(
        main_tex=workspace.main_tex,
        references_bib=workspace.references_bib,
        updated_at=workspace.updated_at,
    )


@router.get("/history", response_model=list[WorkspaceVersionMetadata])
def get_latex_workspace_history(
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
        for version, author_name in list_file_versions(db, project_id, "latex")
    ]


@router.post("/history/{version_id}/restore", response_model=LatexWorkspaceResponse)
def restore_latex_workspace_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: WorkspaceRestoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    workspace = _get_workspace(db, project_id)
    expected = payload.expected_updated_at
    current_updated_at = workspace.updated_at if workspace else None
    if expected is not None and expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    if current_updated_at is not None and current_updated_at.tzinfo is None:
        current_updated_at = current_updated_at.replace(tzinfo=timezone.utc)
    if expected != current_updated_at:
        raise HTTPException(
            status_code=409,
            detail="This workspace changed in another session. Reload the latest version before restoring.",
        )

    version = db.get(ProjectFileVersion, version_id)
    if (
        version is None
        or version.project_id != project_id
        or version.workspace_type != "latex"
        or version.filename not in {"main.tex", "references.bib"}
    ):
        raise HTTPException(status_code=404, detail="LaTeX file version not found.")

    current_main = workspace.main_tex if workspace else DEFAULT_MAIN_TEX
    current_references = workspace.references_bib if workspace else ""
    current_content = current_main if version.filename == "main.tex" else current_references
    if current_content == version.content:
        return LatexWorkspaceResponse(
            main_tex=current_main,
            references_bib=current_references,
            updated_at=current_updated_at,
        )

    if workspace is None:
        workspace = LatexWorkspace(
            project_id=project_id,
            main_tex=current_main,
            references_bib=current_references,
        )
        db.add(workspace)
    elif current_updated_at is not None:
        result = db.execute(
            update(LatexWorkspace)
            .where(
                LatexWorkspace.project_id == project_id,
                _updated_at_condition(db, workspace.updated_at),
            )
            .values(
                **{
                    "main_tex" if version.filename == "main.tex" else "references_bib": version.content,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This workspace changed in another session. Reload the latest version before restoring.",
            )
    if current_updated_at is None:
        if version.filename == "main.tex":
            workspace.main_tex = version.content
        else:
            workspace.references_bib = version.content
        workspace.updated_at = datetime.now(timezone.utc)
    try:
        record_file_version(
            db,
            project_id,
            "latex",
            version.filename,
            current_content,
            user.user_id,
        )
        record_file_version(
            db,
            project_id,
            "latex",
            version.filename,
            version.content,
            user.user_id,
            force=True,
        )
        record_activity(
            db,
            user.user_id,
            "latex_workspace.version_restored",
            {"filename": version.filename, "version_number": version.version_number},
            project_id=project_id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This workspace changed in another session. Reload the latest version before restoring.",
        ) from None
    db.refresh(workspace)
    return LatexWorkspaceResponse(
        main_tex=workspace.main_tex,
        references_bib=workspace.references_bib,
        updated_at=workspace.updated_at,
    )


@router.post("/compile")
def compile_latex_workspace(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    workspace = _get_workspace(db, project_id)
    main_tex = workspace.main_tex if workspace else DEFAULT_MAIN_TEX
    references_bib = workspace.references_bib if workspace else ""
    artifacts = db.scalars(
        select(PythonWorkspaceArtifact).where(
            PythonWorkspaceArtifact.project_id == project_id
        )
    ).all()
    generated_assets = {artifact.filename: artifact.content for artifact in artifacts}
    try:
        pdf = compile_latex(main_tex, references_bib, generated_assets)
    except LatexCompilerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LatexCompilationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="research-draft.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.put("", response_model=LatexWorkspaceResponse)
def save_latex_workspace(
    project_id: uuid.UUID,
    payload: LatexWorkspaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    workspace = _get_workspace(db, project_id)
    if "expected_updated_at" in payload.model_fields_set:
        expected = payload.expected_updated_at
        current = workspace.updated_at if workspace else None
        if expected is not None and expected.tzinfo is None:
            expected = expected.replace(tzinfo=timezone.utc)
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if expected != current:
            raise HTTPException(
                status_code=409,
                detail="This workspace changed in another session. Reload the latest version before saving.",
            )
    original_main = workspace.main_tex if workspace else DEFAULT_MAIN_TEX
    original_references = workspace.references_bib if workspace else ""
    if workspace is None:
        workspace = LatexWorkspace(
            project_id=project_id,
            main_tex=payload.main_tex,
            references_bib=payload.references_bib,
        )
        db.add(workspace)
    elif "expected_updated_at" in payload.model_fields_set:
        result = db.execute(
            update(LatexWorkspace)
            .where(
                LatexWorkspace.project_id == project_id,
                _updated_at_condition(db, workspace.updated_at),
            )
            .values(
                main_tex=payload.main_tex,
                references_bib=payload.references_bib,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This workspace changed in another session. Reload the latest version before saving.",
            )
    else:
        workspace.main_tex = payload.main_tex
        workspace.references_bib = payload.references_bib
        workspace.updated_at = datetime.now(timezone.utc)
    try:
        db.flush()
        record_file_version(db, project_id, "latex", "main.tex", original_main, None)
        record_file_version(db, project_id, "latex", "references.bib", original_references, None)
        record_file_version(db, project_id, "latex", "main.tex", payload.main_tex, user.user_id)
        record_file_version(
            db, project_id, "latex", "references.bib", payload.references_bib, user.user_id
        )
        record_activity(db, user.user_id, "latex_workspace.saved", project_id=project_id)
        db.commit()
    except IntegrityError:
        db.rollback()
        if "expected_updated_at" in payload.model_fields_set:
            raise HTTPException(
                status_code=409,
                detail="This workspace changed in another session. Reload the latest version before saving.",
            ) from None
        raise
    db.refresh(workspace)
    return LatexWorkspaceResponse(
        main_tex=workspace.main_tex,
        references_bib=workspace.references_bib,
        updated_at=workspace.updated_at,
    )
