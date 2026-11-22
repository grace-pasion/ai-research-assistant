import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote
from uuid import UUID

import httpx

from app.config import get_settings

SUPABASE_PATH_PREFIX = "supabase://"


def _supabase_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    if settings.storage_backend != "supabase":
        raise RuntimeError("Supabase storage was requested but STORAGE_BACKEND is not 'supabase'.")
    supabase_key = settings.effective_supabase_key
    if not settings.supabase_url or not supabase_key:
        raise RuntimeError(
            "Supabase storage requires SUPABASE_URL and SUPABASE_SECRET_KEY "
            "(or the legacy SUPABASE_SERVICE_ROLE_KEY)."
        )
    url = settings.supabase_url.rstrip("/")
    key = supabase_key.get_secret_value()
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY cannot be empty.")
    return url, key, settings.supabase_storage_bucket


def _object_url(url: str, bucket: str, object_path: str) -> str:
    return (
        f"{url}/storage/v1/object/{quote(bucket, safe='')}/"
        f"{quote(object_path, safe='/')}"
    )


def _storage_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def is_remote_storage_path(storage_path: str) -> bool:
    return storage_path.startswith(SUPABASE_PATH_PREFIX)


def store_document(
    project_id: UUID,
    document_id: UUID,
    extension: str,
    data: bytes,
    content_type: str | None,
) -> str:
    settings = get_settings()
    object_path = f"{project_id}/{document_id}{extension}"
    if settings.storage_backend == "local":
        path = Path(settings.storage_dir) / object_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    url, key, bucket = _supabase_credentials()
    headers = {
        **_storage_headers(key),
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "false",
    }
    response = httpx.post(
        _object_url(url, bucket, object_path),
        content=data,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()
    return f"{SUPABASE_PATH_PREFIX}{bucket}/{object_path}"


def read_document(storage_path: str) -> bytes:
    if not is_remote_storage_path(storage_path):
        return Path(storage_path).read_bytes()
    bucket, object_path = _parse_remote_path(storage_path)
    url, key, _ = _supabase_credentials()
    response = httpx.get(
        _object_url(url, bucket, object_path),
        headers=_storage_headers(key),
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def delete_document(storage_path: str) -> None:
    if not is_remote_storage_path(storage_path):
        path = Path(storage_path)
        if path.is_file():
            path.unlink()
        return
    bucket, object_path = _parse_remote_path(storage_path)
    url, key, _ = _supabase_credentials()
    response = httpx.request(
        "DELETE",
        f"{url}/storage/v1/object/{quote(bucket, safe='')}",
        json={"prefixes": [object_path]},
        headers=_storage_headers(key),
        timeout=60,
    )
    response.raise_for_status()


@contextmanager
def materialize_document(storage_path: str, suffix: str) -> Iterator[Path]:
    if not is_remote_storage_path(storage_path):
        yield Path(storage_path)
        return

    file_descriptor, temporary_path = tempfile.mkstemp(suffix=suffix)
    os.close(file_descriptor)
    path = Path(temporary_path)
    try:
        path.write_bytes(read_document(storage_path))
        yield path
    finally:
        path.unlink(missing_ok=True)


def _parse_remote_path(storage_path: str) -> tuple[str, str]:
    remote_path = storage_path[len(SUPABASE_PATH_PREFIX) :]
    bucket, separator, object_path = remote_path.partition("/")
    if not separator or not bucket or not object_path:
        raise ValueError("Invalid Supabase storage path.")
    _, _, configured_bucket = _supabase_credentials()
    if bucket != configured_bucket:
        raise ValueError("Document storage bucket does not match SUPABASE_STORAGE_BUCKET.")
    return bucket, object_path
