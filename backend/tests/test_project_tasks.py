import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    Document,
    Notification,
    Paper,
    ProjectInvitation,
    ProjectPaper,
    ProjectTask,
    ResearchProject,
    TeamWorkspace,
    User,
)
from app.routers import project_tasks
from app.schemas import ProjectTaskCreate, ProjectTaskUpdate


@pytest.fixture
def task_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        Document,
        ProjectPaper,
        Annotation,
        ProjectTask,
        Notification,
    ):
        model.__table__.create(research_engine)
    Paper.__table__.create(literature_engine)
    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(
            email="owner@example.com",
            username="owner",
            name="Project owner",
            password_hash="hashed",
        )
        collaborator = User(
            email="collaborator@example.com",
            username="collaborator",
            name="Project collaborator",
            password_hash="hashed",
        )
        outsider = User(
            email="outsider@example.com",
            username="outsider",
            name="Outsider",
            password_hash="hashed",
        )
        db.add_all((owner, collaborator, outsider))
        db.flush()
        project = ResearchProject(user_id=owner.user_id, project_name="Research project")
        db.add(project)
        db.flush()
        document = Document(
            project_id=project.project_id,
            filename="study.txt",
            file_type="txt",
            storage_path="study.txt",
            file_size=20,
            extracted_text="Research text.",
            processing_status="ready",
        )
        paper = Paper(
            external_paper_id="paper-1",
            api_provider="openalex",
            title="Saved study",
            abstract="Research abstract.",
        )
        db.add(document)
        literature_db.add(paper)
        db.flush()
        literature_db.flush()
        db.add_all(
            (
                ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id),
                ProjectInvitation(
                    project_id=project.project_id,
                    inviter_id=owner.user_id,
                    invitee_id=collaborator.user_id,
                    role="comment",
                    status="accepted",
                ),
            )
        )
        annotation = Annotation(
            project_id=project.project_id,
            document_id=document.document_id,
            note="Check this result.",
        )
        db.add(annotation)
        db.commit()
        yield db, literature_db, owner, collaborator, outsider, project, document, paper, annotation
    research_engine.dispose()
    literature_engine.dispose()


def test_task_creation_links_sources_and_notifies_assignee(task_databases):
    db, literature_db, owner, collaborator, _, project, document, _, annotation = task_databases
    created = project_tasks.create_project_task(
        project.project_id,
        ProjectTaskCreate(
            source_type="document",
            source_id=document.document_id,
            annotation_id=annotation.annotation_id,
            title="Review this paper",
            assignee_id=collaborator.user_id,
        ),
        db,
        literature_db,
        owner,
    )

    assert created.title == "Review this paper"
    assert created.source_title == document.filename
    assert created.annotation_id == annotation.annotation_id
    assert created.assignee_id == collaborator.user_id
    notification = db.scalar(select(Notification).where(Notification.kind == "task_assigned"))
    assert notification is not None
    assert notification.recipient_id == collaborator.user_id
    assert notification.details["task_id"] == str(created.task_id)


def test_task_creation_rejects_non_collaborators_and_mismatched_notes(task_databases):
    db, literature_db, owner, _, outsider, project, document, paper, annotation = task_databases
    with pytest.raises(HTTPException) as outsider_error:
        project_tasks.create_project_task(
            project.project_id,
            ProjectTaskCreate(
                source_type="document",
                source_id=document.document_id,
                title="Review this section",
                assignee_id=outsider.user_id,
            ),
            db,
            literature_db,
            owner,
        )
    assert outsider_error.value.status_code == 422

    with pytest.raises(HTTPException) as annotation_error:
        project_tasks.create_project_task(
            project.project_id,
            ProjectTaskCreate(
                source_type="paper",
                source_id=paper.paper_id,
                annotation_id=annotation.annotation_id,
                title="Check this paper",
                assignee_id=owner.user_id,
            ),
            db,
            literature_db,
            owner,
        )
    assert annotation_error.value.status_code == 404
    assert db.scalar(select(ProjectTask)) is None


def test_assignee_can_update_status_but_cannot_reassign(task_databases):
    db, literature_db, owner, collaborator, _, project, document, _, _ = task_databases
    task = project_tasks.create_project_task(
        project.project_id,
        ProjectTaskCreate(
            source_type="document",
            source_id=document.document_id,
            title="Review this section",
            assignee_id=collaborator.user_id,
        ),
        db,
        literature_db,
        owner,
    )

    updated = project_tasks.update_project_task(
        project.project_id,
        task.task_id,
        ProjectTaskUpdate(status="in_progress"),
        db,
        literature_db,
        collaborator,
    )
    assert updated.status == "in_progress"

    with pytest.raises(HTTPException) as error:
        project_tasks.update_project_task(
            project.project_id,
            task.task_id,
            ProjectTaskUpdate(assignee_id=None),
            db,
            literature_db,
            collaborator,
        )
    assert error.value.status_code == 403


def test_task_remains_updatable_if_paper_is_unsaved(task_databases):
    db, literature_db, owner, collaborator, _, project, _, paper, _ = task_databases
    task = project_tasks.create_project_task(
        project.project_id,
        ProjectTaskCreate(
            source_type="paper",
            source_id=paper.paper_id,
            title="Check this paper",
            assignee_id=collaborator.user_id,
        ),
        db,
        literature_db,
        owner,
    )
    db.delete(db.get(ProjectPaper, (project.project_id, paper.paper_id)))
    db.commit()

    listed = project_tasks.list_project_tasks(project.project_id, db, literature_db, owner)
    assert listed[0].source_title == "Unavailable paper"
    updated = project_tasks.update_project_task(
        project.project_id,
        task.task_id,
        ProjectTaskUpdate(status="done"),
        db,
        literature_db,
        collaborator,
    )
    assert updated.status == "done"
    assert updated.source_title == "Unavailable paper"
