from app.services.academic_search import normalize_crossref, normalize_openalex


def test_normalize_openalex_work_and_rebuild_abstract():
    paper = normalize_openalex(
        {
            "id": "https://openalex.org/W123",
            "title": "A study",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1/example",
            "abstract_inverted_index": {"Evidence": [0], "matters.": [1]},
            "authorships": [
                {"author": {"id": "https://openalex.org/A1", "display_name": "A Researcher"}}
            ],
        }
    )

    assert paper is not None
    assert paper["external_paper_id"] == "W123"
    assert paper["abstract"] == "Evidence matters."
    assert paper["authors"] == [{"id": "A1", "name": "A Researcher"}]


def test_normalize_crossref_uses_doi_and_publication_year():
    paper = normalize_crossref(
        {
            "DOI": "10.1000/example",
            "title": ["A crossref paper"],
            "published-online": {"date-parts": [[2023, 5, 2]]},
            "author": [{"given": "Casey", "family": "Researcher"}],
        }
    )

    assert paper is not None
    assert paper["external_paper_id"] == "10.1000/example"
    assert paper["publication_year"] == 2023
    assert paper["authors"][0]["name"] == "Casey Researcher"


def test_normalizers_skip_incomplete_metadata():
    assert normalize_openalex({"title": "", "id": ""}) is None
    assert normalize_crossref({"title": ["No DOI"]}) is None
