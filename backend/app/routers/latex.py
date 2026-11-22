import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LatexWorkspace, User
from app.schemas import LatexWorkspaceResponse, LatexWorkspaceUpdate
from app.security import get_current_user, require_project_owner
from app.services.audit import record_activity

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
    require_project_owner(db, project_id, user.user_id)
    workspace = _get_workspace(db, project_id)
    if workspace is None:
        return LatexWorkspaceResponse(main_tex=DEFAULT_MAIN_TEX, references_bib="")
    return LatexWorkspaceResponse(
        main_tex=workspace.main_tex,
        references_bib=workspace.references_bib,
    )


@router.put("", response_model=LatexWorkspaceResponse)
def save_latex_workspace(
    project_id: uuid.UUID,
    payload: LatexWorkspaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_owner(db, project_id, user.user_id)
    workspace = _get_workspace(db, project_id)
    if workspace is None:
        workspace = LatexWorkspace(
            project_id=project_id,
            main_tex=payload.main_tex,
            references_bib=payload.references_bib,
        )
        db.add(workspace)
    else:
        workspace.main_tex = payload.main_tex
        workspace.references_bib = payload.references_bib
    record_activity(db, user.user_id, "latex_workspace.saved")
    db.commit()
    return LatexWorkspaceResponse(
        main_tex=workspace.main_tex,
        references_bib=workspace.references_bib,
    )
