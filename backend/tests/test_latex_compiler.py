import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.services import latex_compiler
from app.services.latex_compiler import (
    LatexCompilationError,
    LatexCompilerUnavailable,
    LatexFormatterUnavailable,
    LatexFormattingError,
    _citation_key_locations,
    _format_compiler_output,
    citation_key_issues,
    compile_latex,
    format_latex_source,
)


def test_citation_key_issues_ignore_comments_and_report_missing_or_duplicate_keys():
    issues = citation_key_issues(
        r"\citep[see][p. 10]{found, missing} % \cite{ignored}",
        "@article{found, title={First}}\n@book{found, title={Duplicate}}",
    )
    assert issues == {"missing_keys": ["missing"], "duplicate_keys": ["found"]}


def test_citation_key_issues_distinguish_escaped_percent_signs_from_comments():
    assert citation_key_issues(
        r"\% literal \cite{known} \\% \cite{commented}" + "\n",
        "@article{known, title={Study}}",
    ) == {"missing_keys": [], "duplicate_keys": []}


def test_compiler_checks_citations_before_requiring_texlive():
    with pytest.raises(LatexCompilationError, match="missing2024"):
        compile_latex("\\section{Results}\n\\cite{missing2024}", "")


def test_citation_errors_include_editable_source_file_and_line():
    with pytest.raises(LatexCompilationError, match=r"main\.tex:2"):
        compile_latex("\\section{Results}\n\\cite{missing2024}", "")
    with pytest.raises(LatexCompilationError, match=r"references\.bib:2"):
        compile_latex(
            "\\cite{known}",
            "@article{known, title={First}}\n@book{known, title={Duplicate}}",
        )


def test_compiler_output_replaces_temporary_paths_with_source_filenames():
    formatted = _format_compiler_output(
        "/tmp/fieldnotes/source/main.tex:17: Undefined control sequence."
    )
    assert formatted == "main.tex:17: Undefined control sequence."
    assert _citation_key_locations("\\cite{first, missing}\n", ["missing"]) == {"missing": 1}


def test_compiler_runs_bibtex_and_pdflatex_without_shell_escape(monkeypatch):
    calls = []
    copied_assets = {}

    def which(binary):
        return (
            f"/usr/bin/{binary}"
            if binary in {"prlimit", "runuser", "pdflatex", "bibtex"}
            else None
        )

    def fake_run(command, *, cwd, env, **kwargs):
        calls.append((command, cwd, env, kwargs))
        if any("pdflatex" in argument for argument in command):
            source_file = Path(next(argument for argument in command if argument.endswith("main.tex")))
            asset_dir = source_file.parent / "python-output"
            copied_assets["figure.png"] = (asset_dir / "figure.png").read_bytes()
            copied_assets["table.tex"] = (asset_dir / "table.tex").read_text(encoding="utf-8")
            output_dir = next(
                argument.split("=", 1)[1]
                for argument in command
                if argument.startswith("-output-directory=")
            )
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "main.pdf"), "wb") as pdf:
                pdf.write(b"%PDF-1.7 compiled test")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(latex_compiler.shutil, "which", which)
    monkeypatch.setattr(latex_compiler.subprocess, "run", fake_run)
    monkeypatch.setattr(os, "chown", lambda *_args: None, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwnam=lambda _name: SimpleNamespace(pw_uid=10002, pw_gid=10002)),
    )

    pdf = compile_latex(
        r"\begin{document}\citep{smith2024}\bibliographystyle{plainnat}"
        r"\bibliography{references}\end{document}",
        "@article{smith2024, title={A study}}",
        {
            "figure.png": b"\x89PNG\r\n\x1a\nfigure-bytes",
            "table.tex": r"\begin{tabular}{c}Study\end{tabular}".encode("utf-8"),
        },
    )

    assert pdf.startswith(b"%PDF-")
    assert copied_assets == {
        "figure.png": b"\x89PNG\r\n\x1a\nfigure-bytes",
        "table.tex": r"\begin{tabular}{c}Study\end{tabular}",
    }
    assert sum(any("pdflatex" in argument for argument in call[0]) for call in calls) == 3
    assert sum(any("bibtex" in argument for argument in call[0]) for call in calls) == 1
    for command, _cwd, env, kwargs in calls:
        if "pdflatex" in command:
            assert "-no-shell-escape" in command
            assert "-halt-on-error" in command
        assert 0 < kwargs["timeout"] <= 20
        assert "API_SECRET" not in repr(env)


def test_compiler_reports_unavailable_texlive(monkeypatch):
    monkeypatch.setattr(latex_compiler.shutil, "which", lambda _binary: None)
    with pytest.raises(LatexCompilerUnavailable, match="pdflatex"):
        compile_latex(r"\begin{document}Hello\end{document}", "")


def test_formatter_returns_a_separate_suggestion_from_the_isolated_tool(monkeypatch):
    source = "\\begin{document}\ntext\n\\end{document}\n"
    formatted = "\\begin{document}\n  text\n\\end{document}\n"
    calls = []

    def which(binary):
        return f"/usr/bin/{binary}" if binary in {"latexindent", "runuser", "prlimit"} else None

    def fake_run(command, *, cwd, env, **kwargs):
        calls.append((command, cwd, env, kwargs))
        input_file = Path(command[-1])
        output_file = Path(next(arg[3:] for arg in command if arg.startswith("-o=")))
        assert input_file.read_bytes() == source.encode("utf-8")
        output_file.write_bytes(formatted.encode("utf-8"))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(latex_compiler.shutil, "which", which)
    monkeypatch.setattr(latex_compiler.subprocess, "run", fake_run)
    monkeypatch.setattr(os, "chown", lambda *_args: None, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwnam=lambda _name: SimpleNamespace(pw_uid=10002, pw_gid=10002)),
    )

    result = format_latex_source(source)

    assert result == formatted
    assert len(calls) == 1
    command, _cwd, env, kwargs = calls[0]
    assert any("latexindent" in argument for argument in command)
    assert "main.tex" in Path(command[-1]).name
    assert kwargs["timeout"] == latex_compiler.FORMAT_TIMEOUT_SECONDS
    assert "API_SECRET" not in repr(env)


def test_formatter_reports_unavailable_tool_and_rejects_empty_source(monkeypatch):
    monkeypatch.setattr(
        latex_compiler.shutil,
        "which",
        lambda binary: None if binary == "latexindent" else f"/usr/bin/{binary}",
    )
    with pytest.raises(LatexFormatterUnavailable, match="unavailable"):
        format_latex_source("\\begin{document}private source\\end{document}")

    with pytest.raises(LatexFormattingError, match="There is no LaTeX source"):
        format_latex_source(" \n ")


def test_compiler_rejects_unsafe_generated_asset_paths_before_invoking_tex():
    with pytest.raises(LatexCompilationError, match="path separators"):
        compile_latex(
            r"\begin{document}Hello\end{document}",
            "",
            {"../outside.tex": r"\input{secret}"},
        )
