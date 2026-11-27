import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Author,
    Paper,
    PaperAuthor,
    PaperScreeningDecision,
    PaperStudyExtraction,
    ProjectActivity,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    TeamWorkspace,
    User,
    UserActivity,
)
from app.routers.papers import export_reference_file, import_reference_file
from app.schemas import PaperImportResponse
from app.services.bibliography import (
    Reference,
    format_references,
    normalize_doi,
    parse_bibtex,
    parse_ris,
    save_references_to_project,
)


@pytest.fixture
def bibliography_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        ProjectPaper,
        PaperScreeningDecision,
        PaperStudyExtraction,
        UserActivity,
        ProjectActivity,
    ):
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)
    with Session(research_engine) as research_db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        research_db.add(user)
        research_db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Field notes")
        research_db.add(project)
        research_db.commit()
        yield research_db, literature_db, user, project
    research_engine.dispose()
    literature_engine.dispose()


def test_normalize_doi_accepts_resolver_urls_and_rejects_malformed_values():
    assert normalize_doi(" https://doi.org/10.1234/ABC. ") == "10.1234/abc"
    assert normalize_doi("DOI:10.1234/AbC") == "10.1234/abc"
    with pytest.raises(ValueError, match="form"):
        normalize_doi("not-a-doi")


def test_parse_ris_supports_repeated_authors_and_continuation_lines():
    references = parse_ris(
        "TY  - JOUR\n"
        "TI  - A careful study\n"
        "AU  - Doe, Jane\n"
        "AU  - Roe, John\n"
        "PY  - 2022/05/01\n"
        "DO  - https://doi.org/10.1234/Study\n"
        "AB  - First line\n"
        "  continued abstract\n"
        "ER  - \n"
    )

    assert len(references) == 1
    assert references[0].authors == ("Doe, Jane", "Roe, John")
    assert references[0].year == 2022
    assert references[0].doi == "10.1234/study"
    assert references[0].abstract == "First line continued abstract"


def test_parse_bibtex_handles_nested_braces_quoted_values_and_corporate_authors():
    reference = parse_bibtex(
        '@article{study2021,\n'
        ' title = {A {Nested} Finding},\n'
        ' author = {{World Health Organization} and Doe, Jane},\n'
        ' year = "2021",\n'
        ' doi = {doi:10.1234/Study},\n'
        ' journal = {Research & Practice}\n'
        '}'
    )[0]

    assert reference.title == "A Nested Finding"
    assert reference.authors == ("World Health Organization", "Doe, Jane")
    assert reference.year == 2021
    assert reference.doi == "10.1234/study"
    assert reference.venue == "Research & Practice"


def test_bibtex_export_round_trips_common_escaped_characters():
    reference = Reference(
        title=r"A 100% useful study ~ with \path",
        authors=("Research & Development",),
        doi="10.1234/study",
        abstract="Costs: $5 #1",
        citation_key="study",
    )

    restored = parse_bibtex(format_references([reference], "bibtex"))[0]

    assert restored.title == reference.title
    assert restored.authors == reference.authors
    assert restored.doi == reference.doi
    assert restored.abstract == reference.abstract


def test_parsers_reject_malformed_records_and_non_http_urls():
    with pytest.raises(ValueError, match="missing a title"):
        parse_ris("TY  - JOUR\nAU  - Doe, Jane\nER  - \n")
    with pytest.raises(ValueError, match="closing delimiter"):
        parse_bibtex("@article{broken, title={Missing close}")
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        parse_ris(
            "TY  - JOUR\nTI  - Unsafe link\nUR  - javascript:alert(1)\nER  - \n"
        )


def test_import_matches_existing_dois_and_only_counts_each_project_reference_once(
    bibliography_databases,
):
    db, literature_db, _, project = bibliography_databases
    existing = Paper(
        external_paper_id="provider-1",
        api_provider="openalex",
        title="Existing paper",
        doi="https://doi.org/10.1234/existing",
    )
    literature_db.add(existing)
    literature_db.commit()

    result = save_references_to_project(
        db,
        literature_db,
        project.project_id,
        [
            Reference(title="Different title", doi="DOI:10.1234/EXISTING"),
            Reference(title="Repeated existing", doi="10.1234/existing"),
            Reference(title="New paper", doi="10.5678/new"),
            Reference(title="Repeated new", doi="https://doi.org/10.5678/NEW"),
            Reference(title="No DOI one"),
            Reference(title="No DOI two"),
        ],
    )

    assert result["added_count"] == 4
    assert result["duplicate_count"] == 2
    assert [row["status"] for row in result["results"]] == [
        "matched",
        "duplicate",
        "imported",
        "duplicate",
        "imported",
        "imported",
    ]
    assert result["results"][0]["paper_id"] == existing.paper_id
    assert len(db.scalars(select(ProjectPaper)).all()) == 4
    assert len(literature_db.scalars(select(Paper)).all()) == 4

    prefixed_doi_paper = Paper(
        external_paper_id="provider-2",
        api_provider="crossref",
        title="Prefixed DOI paper",
        doi="DOI:10.9999/prefixed",
    )
    literature_db.add(prefixed_doi_paper)
    literature_db.commit()
    prefixed_result = save_references_to_project(
        db,
        literature_db,
        project.project_id,
        [Reference(title="Another title", doi="10.9999/prefixed")],
    )
    assert prefixed_result["results"][0]["status"] == "matched"
    assert prefixed_result["results"][0]["paper_id"] == prefixed_doi_paper.paper_id

def test_import_and_export_routes_validate_response_and_emit_ris(bibliography_databases):
    db, literature_db, user, project = bibliography_databases
    response = asyncio.run(
        import_reference_file(
            project.project_id,
            UploadFile(
                file=BytesIO(
                    b"TY  - JOUR\nTI  - Route-level paper\nAU  - Doe, Jane\nDO  - 10.1234/route\nER  - \n"
                ),
                filename="references.ris",
            ),
            db,
            literature_db,
            user,
        )
    )

    validated = PaperImportResponse.model_validate(response)
    exported = export_reference_file(project.project_id, "ris", db, literature_db, user)

    assert validated.added_count == 1
    assert validated.results[0].status == "imported"
    assert exported.media_type == "application/x-research-info-systems; charset=utf-8"
    assert "TI  - Route-level paper" in exported.body.decode()

    bibtex_import = asyncio.run(
        import_reference_file(
            project.project_id,
            UploadFile(
                file=BytesIO(
                    b"@article{bibtex-route, title={BibTeX route paper}, doi={10.5678/bibtex}}"
                ),
                filename="references.bib",
            ),
            db,
            literature_db,
            user,
        )
    )
    exported_bibtex = export_reference_file(project.project_id, "bibtex", db, literature_db, user)

    assert PaperImportResponse.model_validate(bibtex_import).added_count == 1
    assert exported_bibtex.media_type == "application/x-bibtex; charset=utf-8"
    assert "BibTeX route paper" in exported_bibtex.body.decode()


def test_import_route_rejects_unsupported_extensions_and_unowned_projects(
    bibliography_databases,
):
    db, literature_db, user, project = bibliography_databases
    with pytest.raises(HTTPException) as unsupported:
        asyncio.run(
            import_reference_file(
                project.project_id,
                UploadFile(file=BytesIO(b"data"), filename="references.txt"),
                db,
                literature_db,
                user,
            )
        )
    assert unsupported.value.status_code == 415

    other_user = User(email="other@example.com", name="Other", password_hash="hashed")
    with pytest.raises(HTTPException) as unowned:
        asyncio.run(
            import_reference_file(
                project.project_id,
                UploadFile(file=BytesIO(b"data"), filename="references.ris"),
                db,
                literature_db,
                other_user,
            )
        )
    assert unowned.value.status_code == 404
