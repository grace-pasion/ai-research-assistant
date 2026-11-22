from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
import pymupdf
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.database import ensure_document_chunk_page_column
from app.models import (
    DailyEmbeddingUsage,
    Document,
    DocumentChunk,
    ResearchProject,
    UserActivity,
    User,
)
from app.routers import documents as documents_router
from app.services import processing


def create_processing_project(db: Session) -> ResearchProject:
    user = User(email=f"{uuid.uuid4()}@example.com", name="Reader", password_hash="hashed")
    db.add(user)
    db.flush()
    project = ResearchProject(user_id=user.user_id, project_name="Processing tests")
    db.add(project)
    db.flush()
    return project


def create_processing_tables(engine) -> None:
    for model in (User, ResearchProject, DailyEmbeddingUsage, Document, DocumentChunk):
        model.__table__.create(engine)


def test_extracted_text_is_kept_when_embedding_generation_fails(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite://")
    create_processing_tables(engine)
    source = tmp_path / "study.txt"
    source.write_text("Extracted evidence remains available to read and search.", encoding="utf-8")
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            document_id=uuid.uuid4(),
            project_id=project.project_id,
            filename=source.name,
            file_type="txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        monkeypatch.setattr(
            processing,
            "get_settings",
            lambda: SimpleNamespace(
                openai_embedding_model="test-embedding-model",
                daily_embedding_token_limit=50_000,
            ),
        )

        class FakeEmbeddings:
            def create(self, **_kwargs):
                raise RuntimeError("Embedding provider unavailable.")

        monkeypatch.setattr(
            processing,
            "_client",
            lambda: SimpleNamespace(embeddings=FakeEmbeddings()),
        )

        with pytest.raises(RuntimeError, match="Embedding provider unavailable"):
            processing.reprocess_document(db, document)

        db.refresh(document)
        assert document.extracted_text == "Extracted evidence remains available to read and search."
        assert document.processing_status == "failed"
        assert document.processing_error == "Embedding provider unavailable."
    engine.dispose()


def test_extracted_document_is_chunked_for_semantic_queries(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite://")
    create_processing_tables(engine)
    source = tmp_path / "study.txt"
    source_text = "The open-access paper reports useful research evidence."
    source.write_text(source_text, encoding="utf-8")
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            document_id=uuid.uuid4(),
            project_id=project.project_id,
            filename=source.name,
            file_type="txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        monkeypatch.setattr(
            processing,
            "get_settings",
            lambda: SimpleNamespace(
                openai_embedding_model="test-embedding-model",
                daily_embedding_token_limit=50_000,
            ),
        )

        class FakeEmbeddings:
            def create(self, **_kwargs):
                return SimpleNamespace(
                    data=[SimpleNamespace(index=0, embedding=[0.01] * 1536)]
                )

        monkeypatch.setattr(
            processing,
            "_client",
            lambda: SimpleNamespace(embeddings=FakeEmbeddings()),
        )
        processing.reprocess_document(db, document)

        chunks = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.document_id)
        ).all()
        db.refresh(document)
        assert document.processing_status == "ready"
        assert document.extracted_text == source_text
        assert len(chunks) == 1
        assert chunks[0].chunk_text == source_text
        assert chunks[0].page_number is None
        assert chunks[0].embedding is not None
    engine.dispose()


def test_embedding_allowance_blocks_api_call_and_keeps_extracted_text(
    tmp_path: Path, monkeypatch
):
    engine = create_engine("sqlite://")
    create_processing_tables(engine)
    source = tmp_path / "study.txt"
    source_text = "The open-access paper reports useful research evidence."
    source.write_text(source_text, encoding="utf-8")
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            document_id=uuid.uuid4(),
            project_id=project.project_id,
            filename=source.name,
            file_type="txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        monkeypatch.setattr(
            processing,
            "get_settings",
            lambda: SimpleNamespace(
                openai_embedding_model="test-embedding-model",
                daily_embedding_token_limit=1,
            ),
        )
        monkeypatch.setattr(processing, "reserve_daily_embedding_tokens", lambda *_args: False)

        class FakeEmbeddings:
            def create(self, **_kwargs):
                raise AssertionError("Embedding API must not be called when over quota.")

        monkeypatch.setattr(
            processing,
            "_client",
            lambda: SimpleNamespace(embeddings=FakeEmbeddings()),
        )
        processing.reprocess_document(db, document)

        db.refresh(document)
        assert document.extracted_text == source_text
        assert document.processing_status == "quota_exceeded"
        assert "exceeds the remaining daily limit" in document.processing_error
        assert db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.document_id)
        ).all() == []
    engine.dispose()


def test_reprocess_does_not_queue_a_second_job_for_a_processing_document():
    engine = create_engine("sqlite://")
    for model in (User, ResearchProject, Document, UserActivity):
        model.__table__.create(engine)
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            project_id=project.project_id,
            filename="study.txt",
            file_type="txt",
            storage_path="test://study.txt",
            file_size=10,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        tasks = BackgroundTasks()
        user = db.get(User, project.user_id)

        result = documents_router.reprocess(document.document_id, tasks, db, user)

        assert result.processing_status == "processing"
        assert tasks.tasks == []
    engine.dispose()


def test_processing_ignores_a_document_deleted_during_extraction(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'processing.sqlite'}")
    create_processing_tables(engine)
    source = tmp_path / "study.txt"
    source.write_text("Extracted evidence.", encoding="utf-8")
    document_id = uuid.uuid4()
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            document_id=document_id,
            project_id=project.project_id,
            filename=source.name,
            file_type="txt",
            storage_path=str(source),
            file_size=source.stat().st_size,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        monkeypatch.setattr(
            processing,
            "get_settings",
            lambda: SimpleNamespace(
                openai_embedding_model="test-embedding-model",
                daily_embedding_token_limit=50_000,
            ),
        )
        monkeypatch.setattr(processing, "_client", lambda: None)

        def delete_during_extraction(_path, _extension):
            with Session(engine) as concurrent_db:
                concurrent_document = concurrent_db.get(Document, document_id)
                concurrent_db.delete(concurrent_document)
                concurrent_db.commit()
            return [(None, "Extracted evidence.")]

        monkeypatch.setattr(processing, "extract_document_pages", delete_during_extraction)

        processing.reprocess_document(db, document)

        assert db.get(Document, document_id) is None
    engine.dispose()


def test_pdf_chunks_retain_their_page_numbers(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite://")
    create_processing_tables(engine)
    source = tmp_path / "study.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Evidence from the first page.")
    pdf.new_page().insert_text((72, 72), "Evidence from the second page.")
    pdf.save(source)
    pdf.close()
    with Session(engine) as db:
        project = create_processing_project(db)
        document = Document(
            document_id=uuid.uuid4(),
            project_id=project.project_id,
            filename=source.name,
            file_type="pdf",
            storage_path=str(source),
            file_size=source.stat().st_size,
            processing_status="processing",
        )
        db.add(document)
        db.commit()
        monkeypatch.setattr(
            processing,
            "get_settings",
            lambda: SimpleNamespace(
                openai_embedding_model="test-embedding-model",
                daily_embedding_token_limit=50_000,
            ),
        )

        class FakeEmbeddings:
            def create(self, **kwargs):
                return SimpleNamespace(
                    data=[
                        SimpleNamespace(index=index, embedding=[0.01] * 1536)
                        for index, _ in enumerate(kwargs["input"])
                    ]
                )

        monkeypatch.setattr(
            processing,
            "_client",
            lambda: SimpleNamespace(embeddings=FakeEmbeddings()),
        )
        processing.reprocess_document(db, document)

        chunks = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        assert [chunk.page_number for chunk in chunks] == [1, 2]
        assert "first page" in chunks[0].chunk_text
        assert "second page" in chunks[1].chunk_text
    engine.dispose()


def test_page_number_migration_adds_nullable_column_to_existing_chunk_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE document_chunks (chunk_id VARCHAR PRIMARY KEY)"))

    ensure_document_chunk_page_column(engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns("document_chunks")}
    assert columns["page_number"]["nullable"]
    engine.dispose()
