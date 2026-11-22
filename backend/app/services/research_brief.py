import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Literal

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


EXPECTED_HEADERS = (
    "source",
    "research question",
    "methods",
    "sampling",
    "findings",
    "limitations",
    "citations",
)


@dataclass(frozen=True)
class EvidenceMatrixRow:
    source: str
    research_question: str
    methods: str
    sampling: str
    findings: str
    limitations: str
    citations: str

    def cells(self) -> tuple[str, ...]:
        return (
            self.source,
            self.research_question,
            self.methods,
            self.sampling,
            self.findings,
            self.limitations,
            self.citations,
        )


@dataclass(frozen=True)
class BriefSource:
    index: int
    kind: Literal["document", "paper"]
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    page_number: int | None = None


def parse_evidence_matrix(content: str) -> list[EvidenceMatrixRow]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if [cell.casefold() for cell in _split_table_row(line)] == list(EXPECTED_HEADERS)
        ),
        None,
    )
    if header_index is None or header_index + 1 >= len(lines):
        raise ValueError("This response does not contain an evidence comparison matrix.")

    separator = _split_table_row(lines[header_index + 1])
    if len(separator) != len(EXPECTED_HEADERS) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        raise ValueError("The evidence comparison matrix is malformed.")

    rows = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = _split_table_row(line)
        if len(cells) != len(EXPECTED_HEADERS):
            raise ValueError("The evidence comparison matrix contains a malformed row.")
        rows.append(EvidenceMatrixRow(*cells))

    if not rows:
        raise ValueError("The evidence comparison matrix has no source rows.")
    return rows


def citation_indices(*values: str) -> set[int]:
    return {
        int(match.group(1))
        for value in values
        for match in re.finditer(r"\[S(\d+)\]", value)
    }


def create_research_brief(
    conversation_title: str,
    question: str,
    rows: list[EvidenceMatrixRow],
    sources: list[BriefSource],
) -> bytes:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.55)
    section.right_margin = Inches(0.55)

    normal = document.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(9)
    for style_name, size in (("Title", 25), ("Heading 1", 16), ("Heading 2", 11)):
        style = document.styles[style_name]
        style.font.name = "Aptos Display"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(35, 67, 51)

    title = document.add_paragraph(style="Title")
    title.add_run("Research Brief")
    subtitle = document.add_paragraph(style="Subtitle")
    subtitle.add_run(_safe_text(question))
    metadata = document.add_paragraph()
    metadata.paragraph_format.space_after = Pt(14)
    metadata_run = metadata.add_run(
        f"{_safe_text(conversation_title)}  |  Prepared {datetime.now(timezone.utc):%B %d, %Y}  |  "
        f"{len(sources)} cited source{'s' if len(sources) != 1 else ''}"
    )
    metadata_run.font.size = Pt(8)
    metadata_run.font.color.rgb = RGBColor(105, 117, 108)

    document.add_heading("Synthesis", level=1)
    intro = document.add_paragraph(
        "Verified findings are consolidated below by source so disagreements and evidence gaps "
        "remain visible. This summary does not infer consensus beyond the cited excerpts."
    )
    intro.paragraph_format.space_after = Pt(8)
    sources_by_index = {source.index: source for source in sources}
    for row in rows:
        source_indexes = citation_indices(row.citations)
        source_label = ", ".join(
            sources_by_index[index].title for index in sorted(source_indexes)
        )
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(5)
        label = paragraph.add_run(f"{source_label}: ")
        label.bold = True
        if _is_missing_evidence(row.findings):
            paragraph.add_run(f"No findings were verified in the retrieved excerpt. {row.citations}")
        else:
            paragraph.add_run(_safe_text(row.findings))

    document.add_heading("Evidence comparison matrix", level=1)
    table = document.add_table(rows=1, cols=len(EXPECTED_HEADERS))
    table.style = "Table Grid"
    table.autofit = False
    widths = (1.55, 1.35, 1.25, 1.15, 2.0, 1.35, 0.55)
    for index, (header, width) in enumerate(zip(EXPECTED_HEADERS, widths)):
        cell = table.rows[0].cells[index]
        cell.width = Inches(width)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cell.text = header.title()
        _set_cell_shading(cell, "234333")
        for run in cell.paragraphs[0].runs:
            run.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.size = Pt(8)
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    header_marker = OxmlElement("w:tblHeader")
    header_marker.set(qn("w:val"), "true")
    header_properties.append(header_marker)

    for row in rows:
        cells = table.add_row().cells
        for index, (value, width) in enumerate(zip(row.cells(), widths)):
            cells[index].width = Inches(width)
            cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            cells[index].text = _safe_text(value)
            for paragraph in cells[index].paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                for run in paragraph.runs:
                    run.font.size = Pt(7)
            if _is_missing_evidence(value):
                for run in cells[index].paragraphs[0].runs:
                    run.italic = True
                    run.font.color.rgb = RGBColor(116, 121, 116)

    note = document.add_paragraph()
    note.paragraph_format.space_before = Pt(6)
    note_run = note.add_run(
        "Missing evidence means the retrieved excerpt did not establish that field; it does not "
        "prove the full source lacks the information."
    )
    note_run.italic = True
    note_run.font.size = Pt(8)
    note_run.font.color.rgb = RGBColor(105, 117, 108)

    document.add_page_break()
    document.add_heading("Bibliography", level=1)
    for source in sources:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.2)
        paragraph.paragraph_format.first_line_indent = Inches(-0.2)
        paragraph.paragraph_format.space_after = Pt(6)
        citation = paragraph.add_run(f"[S{source.index}] ")
        citation.bold = True
        if source.kind == "paper":
            details = []
            if source.authors:
                details.append(", ".join(source.authors))
            if source.year:
                details.append(f"({source.year})")
            details.append(_safe_text(source.title))
            if source.venue:
                details.append(_safe_text(source.venue))
            paragraph.add_run(". ".join(details) + ".")
            if source.doi:
                paragraph.add_run(f" DOI: {_safe_text(source.doi)}.")
            if source.url and source.url != source.doi:
                paragraph.add_run(f" {_safe_text(source.url)}")
        else:
            page = f", PDF p. {source.page_number}" if source.page_number else ""
            paragraph.add_run(f"{_safe_text(source.title)}. Project document{page}.")

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer_run = footer.add_run("Fieldnotes  ·  Cited research brief")
    footer_run.font.size = Pt(8)
    footer_run.font.color.rgb = RGBColor(105, 117, 108)

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _split_table_row(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    return [cell.strip() for cell in line[1:-1].split("|")]


def _is_missing_evidence(value: str) -> bool:
    return value.strip().casefold() == "[missing evidence]"


def _safe_text(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)


def _set_cell_shading(cell, fill: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)
