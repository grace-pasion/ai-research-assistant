from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services import storage


def test_local_storage_round_trips_and_deletes_file(tmp_path: Path, monkeypatch):
    settings = Settings(storage_backend="local", storage_dir=str(tmp_path))
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    project_id, document_id = uuid4(), uuid4()

    stored_path = storage.store_document(
        project_id, document_id, ".txt", b"private research text", "text/plain"
    )

    assert not storage.is_remote_storage_path(stored_path)
    assert storage.read_document(stored_path) == b"private research text"
    with storage.materialize_document(stored_path, ".txt") as path:
        assert path.read_text() == "private research text"
    storage.delete_document(stored_path)
    assert not Path(stored_path).exists()


def test_supabase_storage_uses_private_object_api_and_temp_processing_file(
    tmp_path: Path, monkeypatch
):
    project_id, document_id = uuid4(), uuid4()
    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key=SecretStr("test-service-role"),
        supabase_storage_bucket="research-documents",
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    calls = {}

    def response(method: str, url: str, content: bytes = b"") -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            request=httpx.Request(method, url),
        )

    def fake_post(url, *, content, headers, timeout):
        calls["post"] = (url, content, headers, timeout)
        return response("POST", url)

    def fake_get(url, *, headers, timeout):
        calls["get"] = (url, headers, timeout)
        return response("GET", url, b"private cloud document")

    def fake_request(method, url, *, json, headers, timeout):
        calls["delete"] = (method, url, json, headers, timeout)
        return response(method, url)

    monkeypatch.setattr(storage.httpx, "post", fake_post)
    monkeypatch.setattr(storage.httpx, "get", fake_get)
    monkeypatch.setattr(storage.httpx, "request", fake_request)

    stored_path = storage.store_document(
        project_id, document_id, ".txt", b"private cloud document", "text/plain"
    )

    assert storage.is_remote_storage_path(stored_path)
    assert calls["post"][2]["Authorization"] == "Bearer test-service-role"
    assert calls["post"][2]["x-upsert"] == "false"
    assert storage.read_document(stored_path) == b"private cloud document"
    with storage.materialize_document(stored_path, ".txt") as path:
        assert path.read_bytes() == b"private cloud document"
        temporary_path = path
    assert not temporary_path.exists()

    storage.delete_document(stored_path)
    assert calls["delete"][0] == "DELETE"
    assert calls["delete"][2]["prefixes"] == [
        f"{project_id}/{document_id}.txt"
    ]


def test_supabase_secret_key_is_sent_without_legacy_bearer_header(
    tmp_path: Path, monkeypatch
):
    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://project.supabase.co",
        supabase_secret_key=SecretStr("sb_secret_test"),
        supabase_storage_bucket="research-documents",
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    captured_headers = {}

    def fake_post(url, *, content, headers, timeout):
        captured_headers.update(headers)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(storage.httpx, "post", fake_post)
    storage.store_document(uuid4(), uuid4(), ".txt", b"text", "text/plain")

    assert captured_headers["apikey"] == "sb_secret_test"
    assert "Authorization" not in captured_headers


def test_supabase_storage_requires_server_credentials(monkeypatch):
    settings = Settings(storage_backend="supabase")
    monkeypatch.setattr(storage, "get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_SECRET_KEY"):
        storage.store_document(uuid4(), uuid4(), ".txt", b"text", "text/plain")


def test_database_urls_normalize_to_installed_psycopg_driver():
    from app.database import make_engine

    for url in (
        "postgres://user:pass@example.com/db",
        "postgresql://user:pass@example.com/db",
    ):
        engine = make_engine(url)
        try:
            assert engine.url.drivername == "postgresql+psycopg"
        finally:
            engine.dispose()
