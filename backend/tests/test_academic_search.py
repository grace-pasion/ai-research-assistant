from types import SimpleNamespace

from pydantic import SecretStr

import app.services.academic_search as academic_search
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


def test_semantic_ranking_can_promote_related_abstracts(monkeypatch):
    class FakeEmbeddings:
        def create(self, **_kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                    SimpleNamespace(index=1, embedding=[0.1, 0.9]),
                    SimpleNamespace(index=2, embedding=[0.9, 0.1]),
                ]
            )

    monkeypatch.setattr(
        academic_search,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key=SecretStr("test-key"),
            openai_embedding_model="test-embedding-model",
        ),
    )
    monkeypatch.setattr(
        academic_search,
        "OpenAI",
        lambda **_kwargs: SimpleNamespace(embeddings=FakeEmbeddings()),
    )
    papers = [
        {"title": "Literal keyword match", "abstract": "Unrelated methods."},
        {"title": "Different wording", "abstract": "Conceptually related evidence."},
    ]

    ranked = academic_search._rerank_semantically("breast cancer detection", papers)

    assert ranked == [papers[1], papers[0]]


def test_semantic_ranking_keeps_provider_order_without_openai_key(monkeypatch):
    papers = [{"title": "First"}, {"title": "Second"}]
    monkeypatch.setattr(
        academic_search,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None),
    )

    assert academic_search._rerank_semantically("topic", papers) == papers


def test_semantic_ranking_uses_rare_topic_terms_to_reduce_false_positives(monkeypatch):
    class FakeEmbeddings:
        def create(self, **_kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                    SimpleNamespace(index=1, embedding=[0.95, 0.312]),
                    SimpleNamespace(index=2, embedding=[0.90, 0.436]),
                ]
            )

    monkeypatch.setattr(
        academic_search,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key=SecretStr("test-key"),
            openai_embedding_model="test-embedding-model",
        ),
    )
    monkeypatch.setattr(
        academic_search,
        "OpenAI",
        lambda **_kwargs: SimpleNamespace(embeddings=FakeEmbeddings()),
    )
    broad_match = {
        "title": "Breast Cancer Detection Research",
        "abstract": "A study of screening methods.",
    }
    specific_match = {
        "title": "SimCLR-based Breast Cancer Classification",
        "abstract": "Contrastive learning improves breast cancer detection.",
    }

    ranked = academic_search._rerank_semantically(
        "SimCLR breast cancer detection",
        [broad_match, specific_match],
    )

    assert ranked == [specific_match, broad_match]
