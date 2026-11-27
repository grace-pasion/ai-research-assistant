import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Annotation,
    Document,
    Notification,
    Paper,
    ProjectPaper,
    ProjectTask,
    ResearchProject,
    User,
)
from app.schemas import ProjectTaskCreate, ProjectTaskResponse, ProjectTaskUpdate
from app.security import get_current_user, require_project_access
from app.services.audit import record_activity
from app.services.notification_preferences import add_notification_if_enabled
from app.services.project_collaboration import list_project_collaborators

router = APIRouter(tags=["project tasks"])


def _resolve_source(
    db: Session,
    literature_db: Session,
    project_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
) -> tuple[Document | None, Paper | None]:
    if source_type == "document":
        document = db.get(Document, source_id)
        if document is None or document.project_id != project_id:
            raise HTTPException(status_code=404, detail="Document not found.")
        return document, None
    if db.get(ProjectPaper, (project_id, source_id)) is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")
    paper = literature_db.get(Paper, source_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Saved paper not found.")
    return None, paper


def _task_source_title(
    db: Session,
    literature_db: Session,
    project_id: uuid.UUID,
    task: ProjectTask,
) -> str:
    if task.document_id is not None:
        document = db.get(Document, task.document_id)
        return (
            document.filename
            if document is not None and document.project_id == project_id
            else "Unavailable document"
        )
    if task.paper_id is not None and db.get(ProjectPaper, (project_id, task.paper_id)) is not None:
        paper = literature_db.get(Paper, task.paper_id)
        if paper is not None:
            return paper.title
    return "Unavailable paper"


def _task_response(
    task: ProjectTask,
    *,
    source_title: str,
    users_by_id: dict[uuid.UUID, User],
) -> ProjectTaskResponse:
    creator = users_by_id[task.created_by]
    assignee = users_by_id.get(task.assignee_id) if task.assignee_id is not None else None
    source_type = "document" if task.document_id is not None else "paper"
    source_id = task.document_id or task.paper_id
    if source_id is None:
        raise HTTPException(status_code=500, detail="Task has no linked source.")
    return ProjectTaskResponse(
        task_id=task.task_id,
        project_id=task.project_id,
        source_type=source_type,
        source_id=source_id,
        source_title=source_title,
        annotation_id=task.annotation_id,
        title=task.title,
        status=task.status,
        created_by=task.created_by,
        created_by_name=creator.name,
        assignee_id=task.assignee_id,
        assignee_name=assignee.name if assignee is not None else None,
        assignee_username=assignee.username if assignee is not None else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get(
    "/api/projects/{project_id}/tasks",
    response_model=list[ProjectTaskResponse],
)
def list_project_tasks(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    tasks = db.scalars(
        select(ProjectTask)
        .where(ProjectTask.project_id == project_id)
        .order_by(ProjectTask.created_at.desc(), ProjectTask.task_id)
    ).all()
    if not tasks:
        return []

    document_ids = {task.document_id for task in tasks if task.document_id is not None}
    documents = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.document_id.in_(document_ids),
        )
    ).all() if document_ids else []
    document_titles = {document.document_id: document.filename for document in documents}

    paper_ids = {task.paper_id for task in tasks if task.paper_id is not None}
    saved_paper_ids = set(
        db.scalars(
            select(ProjectPaper.paper_id).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.paper_id.in_(paper_ids),
            )
        ).all()
    ) if paper_ids else set()
    papers = literature_db.scalars(
        select(Paper).where(Paper.paper_id.in_(saved_paper_ids))
    ).all() if saved_paper_ids else []
    paper_titles = {paper.paper_id: paper.title for paper in papers}

    user_ids = {task.created_by for task in tasks}
    user_ids.update(task.assignee_id for task in tasks if task.assignee_id is not None)
    users = db.scalars(select(User).where(User.user_id.in_(user_ids))).all()
    users_by_id = {person.user_id: person for person in users}
    return [
        _task_response(
            task,
            source_title=(
                document_titles.get(task.document_id, "Unavailable document")
                if task.document_id is not None
                else paper_titles.get(task.paper_id, "Unavailable paper")
            ),
            users_by_id=users_by_id,
        )
        for task in tasks
    ]


@router.post(
    "/api/projects/{project_id}/tasks",
    response_model=ProjectTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_task(
    project_id: uuid.UUID,
    payload: ProjectTaskCreate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, user.user_id, "comment")
    document, paper = _resolve_source(
        db, literature_db, project_id, payload.source_type, payload.source_id
    )
    collaborator_roles = {
        person.user_id: role for person, role in list_project_collaborators(db, project)
    }
    if payload.assignee_id not in collaborator_roles:
        raise HTTPException(status_code=422, detail="The assignee must be a project collaborator.")

    if payload.annotation_id is not None:
        annotation = db.scalar(
            select(Annotation).where(
                Annotation.annotation_id == payload.annotation_id,
                Annotation.project_id == project_id,
                Annotation.document_id == (
                    payload.source_id if payload.source_type == "document" else None
                ),
                Annotation.paper_id == (
                    payload.source_id if payload.source_type == "paper" else None
                ),
            )
        )
        if annotation is None:
            raise HTTPException(
                status_code=404,
                detail="The annotation must belong to the selected source and project.",
            )

    task = ProjectTask(
        project_id=project_id,
        document_id=document.document_id if document is not None else None,
        paper_id=paper.paper_id if paper is not None else None,
        annotation_id=payload.annotation_id,
        created_by=user.user_id,
        assignee_id=payload.assignee_id,
        title=payload.title,
    )
    db.add(task)
    db.flush()
    record_activity(db, user.user_id, "project_task.created", project_id=project_id)
    if payload.assignee_id != user.user_id:
        add_notification_if_enabled(
            db,
            Notification(
                recipient_id=payload.assignee_id,
                actor_id=user.user_id,
                kind="task_assigned",
                project_id=project_id,
                details={
                    "task_id": str(task.task_id),
                    "task_title": task.title,
                    "source_type": payload.source_type,
                    "source_id": str(payload.source_id),
                    "source_title": document.filename if document is not None else paper.title,
                },
            ),
        )
    db.commit()
    db.refresh(task)
    users = db.scalars(
        select(User).where(User.user_id.in_({task.created_by, task.assignee_id}))
    ).all()
    return _task_response(
        task,
        source_title=document.filename if document is not None else paper.title,
        users_by_id={person.user_id: person for person in users},
    )


@router.patch(
    "/api/projects/{project_id}/tasks/{task_id}",
    response_model=ProjectTaskResponse,
)
def update_project_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ProjectTaskUpdate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, user.user_id)
    task = db.scalar(
        select(ProjectTask).where(
            ProjectTask.task_id == task_id,
            ProjectTask.project_id == project_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    is_owner = project.user_id == user.user_id
    is_creator = task.created_by == user.user_id
    is_assignee = task.assignee_id == user.user_id
    if "assignee_id" in payload.model_fields_set and not (is_owner or is_creator):
        raise HTTPException(status_code=403, detail="Only the task creator or project owner can reassign it.")
    if payload.status is not None and not (is_owner or is_creator or is_assignee):
        raise HTTPException(status_code=403, detail="Only the task creator, assignee, or project owner can update it.")
    if payload.assignee_id is not None:
        collaborators = {
            person.user_id
            for person, _ in list_project_collaborators(db, project)
        }
        if payload.assignee_id not in collaborators:
            raise HTTPException(status_code=422, detail="The assignee must be a project collaborator.")

    previous_assignee_id = task.assignee_id
    source_title = _task_source_title(db, literature_db, project_id, task)
    if "assignee_id" in payload.model_fields_set:
        task.assignee_id = payload.assignee_id
    if payload.status is not None:
        task.status = payload.status
    if (
        task.assignee_id is not None
        and task.assignee_id != previous_assignee_id
        and task.assignee_id != user.user_id
    ):
        add_notification_if_enabled(
            db,
            Notification(
                recipient_id=task.assignee_id,
                actor_id=user.user_id,
                kind="task_assigned",
                project_id=project_id,
                details={
                    "task_id": str(task.task_id),
                    "task_title": task.title,
                    "source_type": "document" if task.document_id is not None else "paper",
                    "source_id": str(task.document_id or task.paper_id),
                    "source_title": source_title,
                },
            ),
        )
    record_activity(db, user.user_id, "project_task.updated", project_id=project_id)
    db.commit()
    db.refresh(task)
    user_ids = {task.created_by}
    if task.assignee_id is not None:
        user_ids.add(task.assignee_id)
    users = db.scalars(select(User).where(User.user_id.in_(user_ids))).all()
    return _task_response(
        task,
        source_title=source_title,
        users_by_id={person.user_id: person for person in users},
    )


@router.delete(
    "/api/projects/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = require_project_access(db, project_id, user.user_id)
    task = db.scalar(
        select(ProjectTask).where(
            ProjectTask.task_id == task_id,
            ProjectTask.project_id == project_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.created_by != user.user_id and project.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Only the task creator or project owner can delete it.")
    record_activity(db, user.user_id, "project_task.deleted", project_id=project_id)
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
