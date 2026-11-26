import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, get_literature_db
from app.models import (
    Document,
    Paper,
    ProjectCollection,
    ProjectCollectionItem,
    ProjectPaper,
    User,
)
from app.schemas import (
    ProjectCollectionCreate,
    ProjectCollectionItemCreate,
    ProjectCollectionItemResponse,
    ProjectCollectionResponse,
    ProjectCollectionUpdate,
)
from app.security import get_current_user, require_project_access

router = APIRouter(tags=["project collections"])


def _collection_responses(
    collections: list[ProjectCollection],
    db: Session,
    literature_db: Session,
) -> list[ProjectCollectionResponse]:
    if not collections:
        return []

    collection_ids = [collection.collection_id for collection in collections]
    items = db.scalars(
        select(ProjectCollectionItem)
        .where(ProjectCollectionItem.collection_id.in_(collection_ids))
        .order_by(ProjectCollectionItem.added_at, ProjectCollectionItem.item_id)
    ).all()
    document_ids = {
        item.document_id
        for item in items
        if item.source_type == "document" and item.document_id is not None
    }
    paper_ids = {
        item.paper_id
        for item in items
        if item.source_type == "paper" and item.paper_id is not None
    }
    documents_by_id = {
        document.document_id: document.filename
        for document in db.scalars(
            select(Document).where(Document.document_id.in_(document_ids))
        ).all()
    } if document_ids else {}
    papers_by_id = {
        paper.paper_id: paper.title
        for paper in literature_db.scalars(
            select(Paper).where(Paper.paper_id.in_(paper_ids))
        ).all()
    } if paper_ids else {}

    items_by_collection: dict[uuid.UUID, list[ProjectCollectionItemResponse]] = {
        collection_id: [] for collection_id in collection_ids
    }
    for item in items:
        if item.source_type == "document":
            source_id = item.document_id
            source_title = documents_by_id.get(source_id)
        else:
            source_id = item.paper_id
            source_title = papers_by_id.get(source_id)
        if source_id is None:
            raise RuntimeError("Collection item has no source identifier.")
        items_by_collection[item.collection_id].append(
            ProjectCollectionItemResponse(
                item_id=item.item_id,
                source_type=item.source_type,
                source_id=source_id,
                source_title=source_title,
                added_at=item.added_at,
            )
        )

    return [
        ProjectCollectionResponse(
            collection_id=collection.collection_id,
            project_id=collection.project_id,
            name=collection.name,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            items=items_by_collection[collection.collection_id],
        )
        for collection in collections
    ]


def _get_project_collection(
    db: Session,
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
) -> ProjectCollection:
    collection = db.scalar(
        select(ProjectCollection).where(
            ProjectCollection.collection_id == collection_id,
            ProjectCollection.project_id == project_id,
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found.")
    return collection


@router.get(
    "/api/projects/{project_id}/collections",
    response_model=list[ProjectCollectionResponse],
)
def list_project_collections(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id)
    collections = db.scalars(
        select(ProjectCollection)
        .where(ProjectCollection.project_id == project_id)
        .order_by(ProjectCollection.created_at.desc(), ProjectCollection.name)
    ).all()
    return _collection_responses(list(collections), db, literature_db)


@router.post(
    "/api/projects/{project_id}/collections",
    response_model=ProjectCollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_collection(
    project_id: uuid.UUID,
    payload: ProjectCollectionCreate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    collection = ProjectCollection(
        project_id=project_id,
        name=payload.name,
        normalized_name=payload.name.casefold(),
    )
    db.add(collection)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A collection with this name already exists in the project.",
        ) from exc
    db.refresh(collection)
    return _collection_responses([collection], db, literature_db)[0]


@router.patch(
    "/api/projects/{project_id}/collections/{collection_id}",
    response_model=ProjectCollectionResponse,
)
def update_project_collection(
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
    payload: ProjectCollectionUpdate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    collection = _get_project_collection(db, project_id, collection_id)
    collection.name = payload.name
    collection.normalized_name = payload.name.casefold()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A collection with this name already exists in the project.",
        ) from exc
    db.refresh(collection)
    return _collection_responses([collection], db, literature_db)[0]


@router.delete(
    "/api/projects/{project_id}/collections/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_collection(
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    collection = _get_project_collection(db, project_id, collection_id)
    db.execute(
        delete(ProjectCollectionItem).where(
            ProjectCollectionItem.collection_id == collection_id
        )
    )
    db.delete(collection)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/projects/{project_id}/collections/{collection_id}/items",
    response_model=ProjectCollectionItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_collection_item(
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
    payload: ProjectCollectionItemCreate,
    db: Session = Depends(get_db),
    literature_db: Session = Depends(get_literature_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    collection = _get_project_collection(db, project_id, collection_id)
    if payload.source_type == "document":
        document = db.scalar(
            select(Document).where(
                Document.document_id == payload.source_id,
                Document.project_id == project_id,
            )
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Project document not found.")
        duplicate_query = select(ProjectCollectionItem.item_id).where(
            ProjectCollectionItem.collection_id == collection.collection_id,
            ProjectCollectionItem.document_id == payload.source_id,
        )
        item = ProjectCollectionItem(
            collection_id=collection.collection_id,
            source_type="document",
            document_id=payload.source_id,
        )
        source_title = document.filename
    else:
        if db.get(ProjectPaper, (project_id, payload.source_id)) is None:
            raise HTTPException(status_code=404, detail="Saved paper not found in this project.")
        paper = literature_db.get(Paper, payload.source_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Academic paper not found.")
        duplicate_query = select(ProjectCollectionItem.item_id).where(
            ProjectCollectionItem.collection_id == collection.collection_id,
            ProjectCollectionItem.paper_id == payload.source_id,
        )
        item = ProjectCollectionItem(
            collection_id=collection.collection_id,
            source_type="paper",
            paper_id=payload.source_id,
        )
        source_title = paper.title
    if db.scalar(duplicate_query) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This source is already in the collection.",
        )

    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This source is already in the collection.",
        ) from exc
    db.refresh(item)
    return ProjectCollectionItemResponse(
        item_id=item.item_id,
        source_type=item.source_type,
        source_id=payload.source_id,
        source_title=source_title,
        added_at=item.added_at,
    )


@router.delete(
    "/api/projects/{project_id}/collections/{collection_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_collection_item(
    project_id: uuid.UUID,
    collection_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_project_access(db, project_id, user.user_id, "edit")
    _get_project_collection(db, project_id, collection_id)
    item = db.scalar(
        select(ProjectCollectionItem).where(
            ProjectCollectionItem.collection_id == collection_id,
            ProjectCollectionItem.item_id == item_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Collection item not found.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
