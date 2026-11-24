import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services import latex_compiler
from app.services.latex_compiler import (
    LatexCompilationError,
    LatexCompilerUnavailable,
    citation_key_issues,
    compile_latex,
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
        compile_latex(r"\cite{missing2024}", "")


def test_compiler_runs_bibtex_and_pdflatex_without_shell_escape(monkeypatch):
    calls = []

    def which(binary):
        return (
            f"/usr/bin/{binary}"
            if binary in {"prlimit", "runuser", "pdflatex", "bibtex"}
            else None
        )

    def fake_run(command, *, cwd, env, **kwargs):
        calls.append((command, cwd, env, kwargs))
        if any("pdflatex" in argument for argument in command):
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
    )

    assert pdf.startswith(b"%PDF-")
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
