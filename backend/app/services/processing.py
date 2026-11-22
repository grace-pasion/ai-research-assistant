import uuid
from pathlib import Path

from openai import OpenAI
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, DocumentChunk
from app.services.documents import estimate_tokens, extract_text, split_text
from app.services.storage import materialize_document


def _client() -> OpenAI | None:
    api_key = get_settings().openai_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        return None
    return OpenAI(api_key=api_key.get_secret_value())


def reprocess_document(db: Session, document: Document) -> None:
    settings = get_settings()
    document.processing_status = "processing"
    document.processing_error = None
    db.commit()
    try:
        with materialize_document(
            document.storage_path,
            Path(document.filename).suffix.lower(),
        ) as path:
            text = extract_text(path, Path(document.filename).suffix.lower())
        chunks = split_text(text)
        if not text or not chunks:
            raise ValueError("No readable text was found in this file.")

        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.document_id))
        document.extracted_text = text
        client = _client()
        vectors: list[list[float] | None] = [None] * len(chunks)
        if client is not None:
            for start in range(0, len(chunks), 64):
                batch = chunks[start : start + 64]
                result = client.embeddings.create(
                    model=settings.openai_embedding_model,
                    input=batch,
                )
                for item in result.data:
                    vectors[start + item.index] = item.embedding

        db.add_all(
            [
                DocumentChunk(
                    document_id=document.document_id,
                    chunk_index=index,
                    chunk_text=chunk,
                    embedding=vectors[index],
                    token_count=estimate_tokens(chunk),
                )
                for index, chunk in enumerate(chunks)
            ]
        )
        document.processing_status = "ready" if client is not None else "needs_api_key"
        if client is None:
            document.processing_error = (
                "Text is available, but semantic search needs OPENAI_API_KEY. "
                "Set it in the root .env file and select Reprocess."
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        current = db.get(Document, document.document_id)
        if current is None:
            raise
        current.processing_status = "failed"
        current.processing_error = str(exc)[:1000]
        db.commit()
        raise

