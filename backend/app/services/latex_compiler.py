import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from app.services.python_workspace import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    MAX_ARTIFACT_TOTAL_BYTES,
    validate_artifact,
)

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_COMPILE_FILE_BYTES = 30 * 1024 * 1024
COMPILE_TIMEOUT_SECONDS = 20
LATEX_COMMANDS = ("pdflatex", "bibtex")
CITATION_COMMANDS = {
    "cite",
    "citep",
    "citet",
    "citealp",
    "citealt",
    "citeauthor",
    "citeyear",
    "citeyearpar",
    "nocite",
}
SOURCE_LOCATION = re.compile(
    r"(?P<path>(?:[A-Za-z]:)?[^\r\n:]*[/\\](?:main\.tex|references\.bib)"
    r"|(?:main\.tex|references\.bib)):(?P<line>\d+):",
    re.IGNORECASE,
)


class LatexCompilerUnavailable(RuntimeError):
    pass


class LatexCompilationError(ValueError):
    pass


def _without_comments(source: str) -> str:
    lines = []
    for line in source.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        backslashes = 0
        for index, character in enumerate(body):
            if character == "%" and backslashes % 2 == 0:
                body = body[:index]
                break
            backslashes = backslashes + 1 if character == "\\" else 0
        lines.append(body + ending)
    return "".join(lines)


def citation_key_issues(main_tex: str, references_bib: str) -> dict[str, list[str]]:
    source = _without_comments(main_tex)
    citations: set[str] = set()
    for match in re.finditer(
        r"\\(" + "|".join(sorted(CITATION_COMMANDS, key=len, reverse=True))
        + r")\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]*)\}",
        source,
    ):
        citations.update(
            key.strip()
            for key in match.group(2).split(",")
            if key.strip() and key.strip() != "*"
        )

    bibliography: list[str] = []
    for match in re.finditer(
        r"(?im)^\s*@([a-z]+)\s*\{\s*([^,\s]+)\s*,",
        _without_comments(references_bib),
    ):
        if match.group(1).casefold() not in {"comment", "preamble", "string"}:
            bibliography.append(match.group(2).strip())
    key_counts = Counter(bibliography)
    keys = set(key_counts)
    return {
        "missing_keys": sorted(citations - keys),
        "duplicate_keys": sorted(key for key, count in key_counts.items() if count > 1),
    }


def _citation_key_locations(source: str, keys: list[str], *, bibliography: bool = False) -> dict[str, int]:
    wanted = set(keys)
    if not wanted:
        return {}
    source = _without_comments(source)
    pattern = (
        r"(?im)^\s*@([a-z]+)\s*\{\s*([^,\s]+)\s*,"
        if bibliography
        else r"\\("
        + "|".join(sorted(CITATION_COMMANDS, key=len, reverse=True))
        + r")\*?(?:\s*\[[^\]]*\]){0,2}\s*\{([^{}]*)\}"
    )
    locations: dict[str, int] = {}
    for match in re.finditer(pattern, source):
        if bibliography and match.group(1).casefold() in {"comment", "preamble", "string"}:
            continue
        raw_keys = [match.group(2)] if bibliography else match.group(2).split(",")
        for raw_key in raw_keys:
            key = raw_key.strip()
            if key not in wanted:
                continue
            start = match.start(2) + match.group(2).find(raw_key)
            locations[key] = source.count("\n", 0, start) + 1
    return locations


def _format_compiler_output(details: str) -> str:
    return SOURCE_LOCATION.sub(
        lambda match: (
            match.group("path").replace("\\", "/").rsplit("/", 1)[-1]
            + ":"
            + match.group("line")
            + ":"
        ),
        details,
    )


def _command(binary: str, args: list[str]) -> list[str]:
    runuser = shutil.which("runuser")
    prlimit = shutil.which("prlimit")
    if runuser is None or prlimit is None:
        raise LatexCompilerUnavailable(
            "The isolated PDF compiler is unavailable on this server. Use the Docker API deployment."
        )
    return [
        prlimit,
        f"--fsize={MAX_COMPILE_FILE_BYTES}:{MAX_COMPILE_FILE_BYTES}",
        "--",
        runuser,
        "--preserve-environment",
        "--user",
        "latex",
        "--",
        binary,
        *args,
    ]


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
) -> subprocess.CompletedProcess[str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LatexCompilationError(
            "PDF compilation exceeded the 20-second limit. Check for expensive macros or loops."
        )
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=remaining,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LatexCompilationError(
                "PDF compilation exceeded the 20-second limit. Check for expensive macros or loops."
            ) from exc
        if result.returncode:
            log.seek(max(0, log.tell() - 4000))
            details = log.read().decode("utf-8", errors="replace").strip()
            details = details or "The TeX compiler did not provide an error message."
            details = _format_compiler_output(details)
            raise LatexCompilationError(f"PDF compilation failed:\n{details}")
    return result


def _validate_assets(assets: Mapping[str, bytes] | None) -> dict[str, bytes]:
    if not assets:
        return {}
    if len(assets) > MAX_ARTIFACT_COUNT:
        raise LatexCompilationError("A maximum of 20 generated outputs can be included.")
    total_bytes = 0
    validated: dict[str, bytes] = {}
    for filename, content in assets.items():
        try:
            validate_artifact(filename, content)
        except ValueError as exc:
            raise LatexCompilationError(str(exc)) from exc
        if len(content) > MAX_ARTIFACT_BYTES:
            raise LatexCompilationError(f"{filename} exceeds the 5 MB per-file limit.")
        total_bytes += len(content)
        if total_bytes > MAX_ARTIFACT_TOTAL_BYTES:
            raise LatexCompilationError("Generated outputs exceed the 20 MB limit.")
        validated[filename] = content
    return validated


def compile_latex(
    main_tex: str,
    references_bib: str,
    assets: Mapping[str, bytes] | None = None,
) -> bytes:
    issues = citation_key_issues(main_tex, references_bib)
    if issues["missing_keys"]:
        locations = _citation_key_locations(main_tex, issues["missing_keys"])
        keys = ", ".join(
            f"{key} (main.tex:{locations[key]})" if key in locations else key
            for key in issues["missing_keys"]
        )
        raise LatexCompilationError(f"Missing BibTeX entries for citation keys: {keys}")
    if issues["duplicate_keys"]:
        locations = _citation_key_locations(
            references_bib, issues["duplicate_keys"], bibliography=True
        )
        keys = ", ".join(
            f"{key} (references.bib:{locations[key]})" if key in locations else key
            for key in issues["duplicate_keys"]
        )
        raise LatexCompilationError(f"Duplicate BibTeX citation keys: {keys}")
    validated_assets = _validate_assets(assets)

    binaries = {name: shutil.which(name) for name in LATEX_COMMANDS}
    if binaries["pdflatex"] is None:
        raise LatexCompilerUnavailable("PDF compilation is unavailable: pdflatex is not installed.")
    if shutil.which("runuser") is None or shutil.which("prlimit") is None:
        raise LatexCompilerUnavailable(
            "The isolated PDF compiler is unavailable on this server. Use the Docker API deployment."
        )
    if "\\bibliography" in _without_comments(main_tex) and references_bib.strip():
        if binaries["bibtex"] is None:
            raise LatexCompilerUnavailable("PDF compilation is unavailable: bibtex is not installed.")
    try:
        import pwd
    except ImportError as exc:
        raise LatexCompilerUnavailable(
            "The isolated PDF compiler is available only in the Docker API deployment."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="fieldnotes-latex-") as directory:
        root = Path(directory)
        source_dir = root / "source"
        build_dir = root / "build"
        source_dir.mkdir(mode=0o755)
        build_dir.mkdir(mode=0o700)
        source_file = source_dir / "main.tex"
        source_file.write_text(main_tex, encoding="utf-8")
        (source_dir / "references.bib").write_text(references_bib, encoding="utf-8")
        source_file.chmod(0o644)
        (source_dir / "references.bib").chmod(0o644)
        if validated_assets:
            asset_dir = source_dir / "python-output"
            asset_dir.mkdir(mode=0o755)
            for filename, content in validated_assets.items():
                asset_file = asset_dir / filename
                asset_file.write_bytes(content)
                asset_file.chmod(0o644)
        root.chmod(0o755)

        latex_user = pwd.getpwnam("latex")
        os.chown(build_dir, latex_user.pw_uid, latex_user.pw_gid)
        env = {
            "PATH": os.pathsep.join(
                {
                    str(Path(binary).parent)
                    for binary in binaries.values()
                    if binary is not None
                }
                | {"/usr/bin", "/bin"}
            ),
            "HOME": str(build_dir),
            "TMPDIR": str(build_dir),
            "TEXMFVAR": str(build_dir / "texmf-var"),
            "TEXMFCONFIG": str(build_dir / "texmf-config"),
            "BIBINPUTS": f"{source_dir}{os.pathsep}",
        }
        deadline = time.monotonic() + COMPILE_TIMEOUT_SECONDS
        latex_args = [
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-synctex=0",
            f"-output-directory={build_dir}",
            str(source_file),
        ]
        _run(_command(binaries["pdflatex"], latex_args), cwd=source_dir, env=env, deadline=deadline)
        if "\\bibliography" in _without_comments(main_tex) and references_bib.strip():
            _run(_command(binaries["bibtex"], ["main"]), cwd=build_dir, env=env, deadline=deadline)
            _run(_command(binaries["pdflatex"], latex_args), cwd=source_dir, env=env, deadline=deadline)
        _run(_command(binaries["pdflatex"], latex_args), cwd=source_dir, env=env, deadline=deadline)

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.is_file():
            raise LatexCompilationError("The TeX compiler completed without producing a PDF.")
        if pdf_path.stat().st_size > MAX_PDF_BYTES:
            raise LatexCompilationError("The generated PDF exceeds the 25 MB download limit.")
        return pdf_path.read_bytes()
