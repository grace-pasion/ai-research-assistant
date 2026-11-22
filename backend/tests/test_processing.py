from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services import processing


def test_extracted_text_is_kept_when_embedding_generation_fails(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite://")
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    source = tmp_path / "study.txt"
    source.write_text("Extracted evidence remains available to read and search.", encoding="utf-8")
    with Session(engine) as db:
        document = Document(
            document_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
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
            lambda: SimpleNamespace(openai_embedding_model="test-embedding-model"),
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
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    source = tmp_path / "study.txt"
    source_text = "The open-access paper reports useful research evidence."
    source.write_text(source_text, encoding="utf-8")
    with Session(engine) as db:
        document = Document(
            document_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
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
            lambda: SimpleNamespace(openai_embedding_model="test-embedding-model"),
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
        assert chunks[0].embedding is not None
    engine.dispose()
