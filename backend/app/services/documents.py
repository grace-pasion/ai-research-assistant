import re
import shutil
from pathlib import Path

import pymupdf
from docx import Document as WordDocument
from PIL import Image
import pytesseract
from PIL import Image

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
CHUNK_WORDS = 450
CHUNK_OVERLAP = 70


def extract_text(path: Path, extension: str) -> str:
    if extension == ".pdf":
        with pymupdf.open(path) as pdf:
            if len(pdf) > 100:
                raise ValueError("PDFs are limited to 100 pages for local text extraction and OCR.")
            pages = []
            for page in pdf:
                page_text = page.get_text("text").strip()
                if not page_text:
                    if shutil.which("tesseract") is None:
                        raise ValueError(
                            "Tesseract OCR is not installed. Install Tesseract and ensure it is "
                            "on PATH to process scanned PDFs."
                        )
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    page_text = pytesseract.image_to_string(image).strip()
                pages.append(page_text)
        text = "\n".join(pages).strip()
        if text:
            return text
        raise ValueError("No readable text was found, even after OCR.")
    if extension == ".docx":
        document = WordDocument(path)
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        tables = [
            " | ".join(cell.text.strip() for cell in row.cells)
            for table in document.tables
            for row in table.rows
        ]
        return "\n".join(paragraphs + tables).strip()
    if extension in {".txt", ".md"}:
        return path.read_text(encoding="utf-8-sig").strip()
    raise ValueError(f"Unsupported document type: {extension}")


def split_text(text: str, max_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    step = max_words - overlap
    return [" ".join(words[start : start + max_words]) for start in range(0, len(words), step)]


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
