import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LatexWorkspace, User
from app.schemas import LatexWorkspaceResponse, LatexWorkspaceUpdate
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.latex_compiler import (
    LatexCompilationError,
    LatexCompilerUnavailable,
    compile_latex,
)

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
    try:
        pdf = compile_latex(main_tex, references_bib)
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
                LatexWorkspace.updated_at == workspace.updated_at,
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
    record_activity(db, user.user_id, "latex_workspace.saved")
    try:
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
