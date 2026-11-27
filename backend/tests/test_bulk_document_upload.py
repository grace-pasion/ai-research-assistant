import asyncio
import uuid
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

import app.routers.documents as documents_router
from app.schemas import BulkDocumentUploadResponse


class FakeDatabase:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1
        for item in self.added:
            item.uploaded_at = datetime.now(timezone.utc)

    def refresh(self, _item):
        return None

    def rollback(self):
        self.rollbacks += 1


def make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def test_bulk_upload_returns_per_file_status_and_schedules_accepted_documents(monkeypatch):
    stored = []
    scheduled = []
    database = FakeDatabase()
    tasks = BackgroundTasks()
    project_id = uuid.uuid4()
    user = SimpleNamespace(user_id=uuid.uuid4())
    monkeypatch.setattr(documents_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(
        documents_router,
        "get_settings",
        lambda: SimpleNamespace(max_upload_mb=1),
    )
    monkeypatch.setattr(
        documents_router,
        "store_document",
        lambda project, document, extension, data, _content_type: (
            stored.append((project, document, extension, data))
            or f"test://{document}{extension}"
        ),
    )
    monkeypatch.setattr(documents_router, "record_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        documents_router,
        "process_saved_document",
        lambda document_id: scheduled.append(document_id),
    )

    response = asyncio.run(
        documents_router.upload_documents(
            project_id,
            tasks,
            [
                make_upload("one.pdf", b"pdf contents"),
                make_upload("unsupported.exe", b"not supported"),
                make_upload("empty.txt", b""),
            ],
            database,
            user,
        )
    )
    validated_response = BulkDocumentUploadResponse.model_validate(response)

    assert [item.filename for item in validated_response.results] == [
        "one.pdf",
        "unsupported.exe",
        "empty.txt",
    ]
    assert response["results"][0]["document"].processing_status == "processing"
    assert response["results"][0]["error"] is None
    assert response["results"][1]["document"] is None
    assert "PDF, DOCX, TXT, or Markdown" in response["results"][1]["error"]
    assert response["results"][2]["document"] is None
    assert "empty" in response["results"][2]["error"]
    assert len(stored) == 1
    assert database.commits == 1
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].args == (response["results"][0]["document"].document_id,)
    assert scheduled == []


def test_bulk_upload_rejects_batches_over_the_limit(monkeypatch):
    monkeypatch.setattr(documents_router, "require_project_access", lambda *_args: None)
    project_id = uuid.uuid4()

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            documents_router.upload_documents(
                project_id,
                BackgroundTasks(),
                [
                    make_upload(f"{index}.txt", b"text")
                    for index in range(documents_router.MAX_BULK_UPLOAD_COUNT + 1)
                ],
                FakeDatabase(),
                SimpleNamespace(user_id=uuid.uuid4()),
            )
        )

    assert error.value.status_code == 413
    assert str(documents_router.MAX_BULK_UPLOAD_COUNT) in error.value.detail
