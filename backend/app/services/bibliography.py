import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Author, Paper, PaperAuthor, ProjectPaper

MAX_BIBLIOGRAPHY_ENTRIES = 1000


@dataclass(frozen=True)
class Reference:
    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    citation_key: str | None = None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = unquote(value).strip().strip("<>")
    doi = re.sub(r"^doi\s*:\s*", "", doi, flags=re.IGNORECASE)
    doi = re.sub(
        r"^(?:https?://)?(?:dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )
    doi = doi.strip().rstrip(".,;").casefold()
    if not doi:
        return None
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
        raise ValueError("DOI must have the form 10.xxxx/identifier.")
    if len(doi) > 255:
        raise ValueError("DOI exceeds the 255-character limit.")
    return doi


def parse_bibtex(content: str) -> list[Reference]:
    content = content.lstrip("\ufeff")
    references = []
    position = 0
    while True:
        entry_start = _find_next_bibtex_entry(content, position)
        if entry_start is None:
            break
        type_start = entry_start + 1
        type_match = re.match(r"[A-Za-z]+", content[type_start:])
        if type_match is None:
            position = type_start
            continue
        entry_type = type_match.group(0).casefold()
        cursor = type_start + type_match.end()
        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if cursor >= len(content) or content[cursor] not in "{(":
            raise ValueError("Malformed BibTeX entry: expected '{' or '('.")
        opening = content[cursor]
        closing = "}" if opening == "{" else ")"
        entry_end = _find_bibtex_entry_end(content, cursor, opening)
        if entry_end is None:
            raise ValueError("Malformed BibTeX entry: missing closing delimiter.")
        position = entry_end + 1
        if entry_type in {"comment", "preamble", "string"}:
            continue

        body_start = cursor + 1
        comma = _find_bibtex_top_level_comma(content, body_start, entry_end, opening)
        if comma is None:
            raise ValueError("Malformed BibTeX entry: missing citation key.")
        citation_key = content[body_start:comma].strip()
        fields = _parse_bibtex_fields(content, comma + 1, entry_end, closing)
        title = _clean_first_field(fields, "title")
        if not title:
            raise ValueError(
                f"BibTeX entry {citation_key or '(unnamed)'} is missing a title."
            )
        authors = _split_bibtex_authors(fields.get("author", ""))
        references.append(
            _make_reference(
                title=title,
                authors=authors,
                year=_parse_year(fields.get("year")),
                doi=fields.get("doi"),
                venue=_clean_first_field(fields, "journal", "booktitle", "series"),
                abstract=_clean_first_field(fields, "abstract"),
                url=_clean_first_field(fields, "url"),
                citation_key=citation_key or None,
            )
        )
        if len(references) > MAX_BIBLIOGRAPHY_ENTRIES:
            raise ValueError(f"A file may contain at most {MAX_BIBLIOGRAPHY_ENTRIES} entries.")

    if not references:
        raise ValueError("No usable BibTeX entries were found.")
    return references


def parse_ris(content: str) -> list[Reference]:
    content = content.lstrip("\ufeff")
    records: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] | None = None
    last_field_index: int | None = None

    for line in content.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^([A-Z0-9]{2})\s{2}-\s?(.*)$", line)
        if match is None:
            if current is None or last_field_index is None:
                raise ValueError("Malformed RIS file: expected a two-letter RIS tag.")
            tag, value = current[last_field_index]
            current[last_field_index] = (tag, f"{value} {line.strip()}".strip())
            continue

        tag, value = match.groups()
        if tag == "TY":
            if current is not None:
                records.append(current)
            current = [(tag, value.strip())]
            last_field_index = 0
        elif tag == "ER":
            if current is not None:
                records.append(current)
            current = None
            last_field_index = None
        elif current is not None:
            current.append((tag, value.strip()))
            last_field_index = len(current) - 1

    if current is not None:
        records.append(current)
    if not records:
        raise ValueError("No RIS records were found.")
    if len(records) > MAX_BIBLIOGRAPHY_ENTRIES:
        raise ValueError(f"A file may contain at most {MAX_BIBLIOGRAPHY_ENTRIES} entries.")

    references = []
    for index, record in enumerate(records, start=1):
        fields: dict[str, list[str]] = {}
        authors = []
        for tag, value in record:
            fields.setdefault(tag, []).append(value)
            if tag in {"AU", "A1"} and value:
                authors.append(value)
        title = _first_ris_field(fields, "TI", "T1")
        if not title:
            raise ValueError(f"RIS record {index} is missing a title.")
        references.append(
            _make_reference(
                title=title,
                authors=authors,
                year=_parse_year(_first_ris_field(fields, "PY", "Y1")),
                doi=_first_ris_field(fields, "DO"),
                venue=_first_ris_field(fields, "JO", "JF", "JA", "T2"),
                abstract=_first_ris_field(fields, "AB", "N2"),
                url=_first_ris_field(fields, "UR", "L1"),
            )
        )
    return references


def save_references_to_project(
    db: Session,
    literature_db: Session,
    project_id: uuid.UUID,
    references: list[Reference],
) -> dict:
    dois = {doi for reference in references if (doi := normalize_doi(reference.doi))}
    variants = {
        variant
        for doi in dois
        for variant in (
            doi,
            f"doi:{doi}",
            f"https://doi.org/{doi}",
            f"http://doi.org/{doi}",
            f"https://dx.doi.org/{doi}",
            f"http://dx.doi.org/{doi}",
        )
    }
    candidates = (
        literature_db.scalars(
            select(Paper).where(func.lower(Paper.doi).in_(variants))
        ).all()
        if variants
        else []
    )
    papers_by_doi: dict[str, Paper] = {}
    for paper in candidates:
        doi = normalize_doi(paper.doi)
        if doi:
            papers_by_doi.setdefault(doi, paper)

    saved_ids = set(
        db.scalars(
            select(ProjectPaper.paper_id).where(ProjectPaper.project_id == project_id)
        ).all()
    )
    saved_candidates = [paper for paper in candidates if paper.paper_id in saved_ids]
    saved_by_doi = {
        doi: paper
        for paper in saved_candidates
        if (doi := normalize_doi(paper.doi))
    }

    results = []
    added_count = 0
    duplicate_count = 0
    try:
        for reference in references:
            doi = normalize_doi(reference.doi)
            paper = saved_by_doi.get(doi) if doi else None
            if paper is None and doi:
                paper = papers_by_doi.get(doi)
            created = paper is None
            if paper is None:
                external_id = doi or uuid.uuid4().hex
                paper = Paper(
                    external_paper_id=external_id,
                    api_provider="import",
                    title=reference.title,
                    abstract=reference.abstract,
                    publication_year=reference.year,
                    doi=doi,
                    paper_url=reference.url or (f"https://doi.org/{doi}" if doi else None),
                    venue=reference.venue,
                )
                literature_db.add(paper)
                literature_db.flush()
                _add_import_authors(literature_db, paper, reference.authors)
                if doi:
                    papers_by_doi[doi] = paper

            if paper.paper_id in saved_ids:
                result_status = "duplicate"
                duplicate_count += 1
            else:
                db.add(
                    ProjectPaper(
                        project_id=project_id,
                        paper_id=paper.paper_id,
                        relationship_type="saved",
                    )
                )
                saved_ids.add(paper.paper_id)
                added_count += 1
                result_status = "imported" if created else "matched"
            results.append(
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "doi": paper.doi,
                    "status": result_status,
                }
            )
        literature_db.commit()
        db.commit()
    except Exception:
        literature_db.rollback()
        db.rollback()
        raise

    return {
        "added_count": added_count,
        "duplicate_count": duplicate_count,
        "results": results,
    }


def format_references(
    references: list[Reference], output_format: Literal["ris", "bibtex"]
) -> str:
    if output_format == "ris":
        return "\n\n".join(_format_ris_record(reference) for reference in references)
    return "\n\n".join(_format_bibtex_entry(reference, index) for index, reference in enumerate(references, 1))


def _add_import_authors(
    literature_db: Session,
    paper: Paper,
    authors: tuple[str, ...],
) -> None:
    for order, name in enumerate(authors):
        external_id = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
        author = literature_db.scalar(
            select(Author).where(
                Author.api_provider == "import",
                Author.external_author_id == external_id,
            )
        )
        if author is None:
            author = Author(
                author_name=name[:255],
                external_author_id=external_id,
                api_provider="import",
            )
            literature_db.add(author)
            literature_db.flush()
        relation = literature_db.get(PaperAuthor, (paper.paper_id, author.author_id))
        if relation is None:
            literature_db.add(
                PaperAuthor(
                    paper_id=paper.paper_id,
                    author_id=author.author_id,
                    author_order=order,
                )
            )


def _find_next_bibtex_entry(content: str, position: int) -> int | None:
    cursor = position
    while cursor < len(content):
        char = content[cursor]
        if char == "%" and (cursor == 0 or content[cursor - 1] != "\\"):
            newline = content.find("\n", cursor)
            cursor = len(content) if newline < 0 else newline + 1
            continue
        if char == "@":
            return cursor
        cursor += 1
    return None


def _find_bibtex_entry_end(content: str, opening_index: int, opening: str) -> int | None:
    escaped = False
    if opening == "{":
        depth = 1
        quoted = False
        for index in range(opening_index + 1, len(content)):
            char = content[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"' and depth == 1:
                quoted = not quoted
            elif not quoted and char == "{":
                depth += 1
            elif not quoted and char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    depth = 1
    brace_depth = 0
    quoted = False
    for index in range(opening_index + 1, len(content)):
        char = content[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"' and brace_depth == 0:
            quoted = not quoted
        elif not quoted and char == "{":
            brace_depth += 1
        elif not quoted and char == "}" and brace_depth:
            brace_depth -= 1
        elif not quoted and brace_depth == 0 and char == "(":
            depth += 1
        elif not quoted and brace_depth == 0 and char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _find_bibtex_top_level_comma(
    content: str, start: int, end: int, opening: str
) -> int | None:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, end):
        char = content[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"' and depth == 0:
            quoted = not quoted
        elif not quoted and char == "{":
            depth += 1
        elif not quoted and char == "}" and depth:
            depth -= 1
        elif not quoted and depth == 0 and char == ",":
            return index
    return None


def _parse_bibtex_fields(
    content: str, position: int, end: int, closing: str
) -> dict[str, str]:
    fields = {}
    while position < end:
        while position < end and (content[position].isspace() or content[position] == ","):
            position += 1
        if position >= end:
            break
        match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", content[position:end])
        if match is None:
            raise ValueError("Malformed BibTeX entry: invalid field name.")
        name = match.group(0).casefold()
        position += match.end()
        while position < end and content[position].isspace():
            position += 1
        if position >= end or content[position] != "=":
            raise ValueError(f"Malformed BibTeX field '{name}': expected '='.")
        value, position = _read_bibtex_value(content, position + 1, end, closing)
        fields[name] = value.strip()
        while position < end and content[position].isspace():
            position += 1
        if position < end and content[position] != ",":
            raise ValueError(f"Malformed BibTeX field '{name}': expected ','.")
    return fields


def _read_bibtex_value(
    content: str, position: int, end: int, closing: str
) -> tuple[str, int]:
    parts = []
    while position < end:
        while position < end and content[position].isspace():
            position += 1
        if position >= end:
            break
        if content[position] == "{":
            value, position = _read_bibtex_braced_value(content, position, end)
        elif content[position] == '"':
            value, position = _read_bibtex_quoted_value(content, position + 1, end)
        else:
            start = position
            while position < end and content[position] not in ",#":
                position += 1
            value = content[start:position].strip()
        parts.append(value)
        while position < end and content[position].isspace():
            position += 1
        if position < end and content[position] == "#":
            position += 1
            continue
        return "".join(parts).strip(), position
    return "".join(parts).strip(), position


def _read_bibtex_braced_value(
    content: str, position: int, end: int
) -> tuple[str, int]:
    depth = 1
    escaped = False
    start = position + 1
    position += 1
    while position < end:
        char = content[position]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start:position], position + 1
        position += 1
    raise ValueError("Malformed BibTeX value: missing closing brace.")


def _read_bibtex_quoted_value(
    content: str, position: int, end: int
) -> tuple[str, int]:
    parts = []
    escaped = False
    while position < end:
        char = content[position]
        if escaped:
            parts.extend(("\\", char))
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return "".join(parts), position + 1
        else:
            parts.append(char)
        position += 1
    raise ValueError("Malformed BibTeX value: missing closing quote.")


def _clean_bibtex_value(value: str) -> str:
    wrappers = re.compile(r"\\(?:emph|textit|textbf|texttt|underline)\s*\{([^{}]*)\}")
    while wrappers.search(value):
        value = wrappers.sub(r"\1", value)
    value = re.sub(r"\\textbackslash\s*\{\}", lambda _: "\\", value)
    value = re.sub(r"\\textasciitilde\s*\{\}", "~", value)
    value = re.sub(r"\\textasciicircum\s*\{\}", "^", value)
    value = re.sub(r"(?<!\\)[{}]", "", value)
    return re.sub(r"\\([&%_$#{}])", r"\1", value).strip()


def _split_bibtex_authors(value: str) -> tuple[str, ...]:
    authors = []
    depth = 0
    escaped = False
    start = 0
    cursor = 0
    while cursor < len(value):
        char = value[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        elif (
            depth == 0
            and value[cursor : cursor + 3].casefold() == "and"
            and (cursor == 0 or value[cursor - 1].isspace())
            and (cursor + 3 == len(value) or value[cursor + 3].isspace())
        ):
            author = _clean_bibtex_value(value[start:cursor])
            if author:
                authors.append(author)
            cursor += 2
            start = cursor + 1
        cursor += 1
    final_author = _clean_bibtex_value(value[start:])
    if final_author:
        authors.append(final_author)
    return tuple(authors)


def _make_reference(
    title: str,
    authors: list[str] | tuple[str, ...],
    year: int | None,
    doi: str | None,
    venue: str | None,
    abstract: str | None,
    url: str | None,
    citation_key: str | None = None,
) -> Reference:
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        raise ValueError("Reference is missing a title.")
    clean_authors = tuple(
        re.sub(r"\s+", " ", author).strip()[:255]
        for author in authors
        if re.sub(r"\s+", " ", author).strip()
    )
    return Reference(
        title=title,
        authors=clean_authors,
        year=year,
        doi=normalize_doi(doi),
        venue=(venue or "").strip()[:512] or None,
        abstract=(abstract or "").strip() or None,
        url=_validate_url(url),
        citation_key=citation_key,
    )


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b\d{4}\b", value)
    return int(match.group(0)) if match else None


def _first_field(fields: dict[str, str], *names: str) -> str | None:
    return next((fields[name].strip() for name in names if fields.get(name, "").strip()), None)


def _clean_first_field(fields: dict[str, str], *names: str) -> str | None:
    value = _first_field(fields, *names)
    return _clean_bibtex_value(value) if value else None


def _first_ris_field(fields: dict[str, list[str]], *names: str) -> str | None:
    return next(
        (fields[name][0].strip() for name in names if fields.get(name) and fields[name][0].strip()),
        None,
    )


def _format_ris_record(reference: Reference) -> str:
    lines = ["TY  - JOUR", f"TI  - {_clean_ris_value(reference.title)}"]
    lines.extend(f"AU  - {_clean_ris_value(author)}" for author in reference.authors)
    if reference.year:
        lines.append(f"PY  - {reference.year}")
    if reference.venue:
        lines.append(f"JO  - {_clean_ris_value(reference.venue)}")
    if reference.doi:
        lines.append(f"DO  - {_clean_ris_value(reference.doi)}")
    if reference.url:
        lines.append(f"UR  - {_clean_ris_value(reference.url)}")
    if reference.abstract:
        lines.append(f"AB  - {_clean_ris_value(reference.abstract)}")
    lines.append("ER  - ")
    return "\n".join(lines)


def _format_bibtex_entry(reference: Reference, index: int) -> str:
    key = re.sub(r"[^A-Za-z0-9:_-]", "", reference.citation_key or "") or f"reference{index}"
    fields = [f"  title = {{{_escape_bibtex(reference.title)}}}"]
    if reference.authors:
        fields.append(
            f"  author = {{{' and '.join(_escape_bibtex(author) for author in reference.authors)}}}"
        )
    if reference.year:
        fields.append(f"  year = {{{reference.year}}}")
    if reference.venue:
        fields.append(f"  journal = {{{_escape_bibtex(reference.venue)}}}")
    if reference.doi:
        fields.append(f"  doi = {{{_escape_bibtex(reference.doi)}}}")
    if reference.url:
        fields.append(f"  url = {{{_escape_bibtex(reference.url)}}}")
    if reference.abstract:
        fields.append(f"  abstract = {{{_escape_bibtex(reference.abstract)}}}")
    return f"@article{{{key},\n" + ",\n".join(fields) + "\n}"


def _escape_bibtex(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    escapes = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(escapes.get(char, char) for char in value)


def _clean_ris_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ")).strip()


def _validate_url(value: str | None) -> str | None:
    url = (value or "").strip()
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Reference URLs must use HTTP or HTTPS.")
    if len(url) > 2048:
        raise ValueError("Reference URLs cannot exceed 2048 characters.")
    return url
