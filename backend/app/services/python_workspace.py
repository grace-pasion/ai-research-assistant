import re
from pathlib import PurePosixPath

MAX_PYTHON_CODE_BYTES = 100_000
MAX_PYTHON_SOURCE_FILE_COUNT = 20
MAX_PYTHON_SOURCE_TOTAL_BYTES = 500_000
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ARTIFACT_COUNT = 20
MAX_INPUT_FILE_BYTES = 5 * 1024 * 1024
MAX_INPUT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_INPUT_FILE_COUNT = 10
MAX_RUN_SNAPSHOT_TOTAL_BYTES = 100 * 1024 * 1024
INPUT_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
ARTIFACT_CONTENT_TYPES = {
    ".png": "image/png",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".tex": "application/x-tex",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_python_source_files(files: list[dict[str, str]]) -> list[dict[str, str]]:
    if not files:
        raise ValueError("A Python workspace must contain at least one source file.")
    if len(files) > MAX_PYTHON_SOURCE_FILE_COUNT:
        raise ValueError(
            f"A Python workspace can contain at most {MAX_PYTHON_SOURCE_FILE_COUNT} source files."
        )

    names: set[str] = set()
    total_bytes = 0
    normalized: list[dict[str, str]] = []
    for source in files:
        filename = source["filename"]
        code = source["code"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,124}\.py", filename, re.IGNORECASE):
            raise ValueError(
                "Python source filenames must be simple .py names without path separators."
            )
        key = filename.casefold()
        if key in names:
            raise ValueError("Python source filenames must be unique regardless of letter case.")
        names.add(key)
        code_bytes = len(code.encode("utf-8"))
        if code_bytes > MAX_PYTHON_CODE_BYTES:
            raise ValueError(f"{filename} exceeds the 100 KB source-file limit.")
        total_bytes += code_bytes
        if total_bytes > MAX_PYTHON_SOURCE_TOTAL_BYTES:
            raise ValueError("Python source files exceed the 500 KB workspace limit.")
        normalized.append({"filename": filename, "code": code})

    if not any(source["filename"] == "main.py" for source in normalized):
        raise ValueError("A source file named exactly main.py is required.")
    return normalized


def validate_artifact_name(filename: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", filename)
        or PurePosixPath(filename).name != filename
    ):
        raise ValueError("Artifact filenames must be simple names without path separators.")
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in ARTIFACT_CONTENT_TYPES:
        raise ValueError("Only PNG, CSV, TSV, and TeX outputs are supported.")
    return ARTIFACT_CONTENT_TYPES[extension]


def validate_artifact(filename: str, content: bytes) -> str:
    content_type = validate_artifact_name(filename)
    if not content:
        raise ValueError(f"{filename} is empty.")
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError(f"{filename} exceeds the 5 MB per-file limit.")
    if content_type == "image/png":
        if not content.startswith(PNG_SIGNATURE):
            raise ValueError(f"{filename} is not a valid PNG file.")
    else:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"{filename} must contain UTF-8 text.") from None
        if "\x00" in text:
            raise ValueError(f"{filename} cannot contain null characters.")
    return content_type
