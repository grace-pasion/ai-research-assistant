from pathlib import Path

import pytest
import pymupdf

from app.services.documents import estimate_tokens, extract_text, split_text


def test_split_text_overlaps_chunks_and_preserves_input():
    words = [f"word{index}" for index in range(1000)]
    chunks = split_text(" ".join(words), max_words=100, overlap=20)

    assert len(chunks) == 13
    assert len(chunks[0].split()) == 100
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]
    assert chunks[-1].split()[-1] == "word999"


@pytest.mark.parametrize("text", ["", "one two three", "a" * 800], ids=["empty", "short", "long-token"])
def test_split_text_handles_empty_and_short_input(text):
    chunks = split_text(text)

    if not text:
        assert chunks == []
    else:
        assert " ".join(chunks[0].split()) == text


def test_text_and_markdown_extraction(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("# Notes\n\nResearch evidence.", encoding="utf-8")

    assert extract_text(source, ".md") == "# Notes\n\nResearch evidence."
    assert estimate_tokens("a" * 100) == 25


def test_extract_searchable_pdf_text(tmp_path: Path):
    source = tmp_path / "source.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A searchable research finding.")
    pdf.save(source)
    pdf.close()

    assert "searchable research finding" in extract_text(source, ".pdf")


def test_unsupported_file_type_is_explicit(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported document type"):
        extract_text(tmp_path / "source.csv", ".csv")
