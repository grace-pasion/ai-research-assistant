from types import SimpleNamespace

import app.services.assistant as assistant
from app.services.assistant import (
    _discover_external_papers,
    _paper_relevance,
    _paper_search_query,
    _requests_external_papers,
)


def test_paper_relevance_prefers_title_matches_and_ignores_unrelated_papers():
    title_match = _paper_relevance(
        "climate adaptation policy",
        "Climate adaptation policy outcomes",
        "A review of regional programs.",
    )
    abstract_match = _paper_relevance(
        "climate adaptation policy",
        "A regional planning review",
        "Climate resilience and adaptation policy are discussed.",
    )
    unrelated = _paper_relevance(
        "climate adaptation policy",
        "A study of protein folding",
        "Methods for predicting molecular structures.",
    )

    assert title_match > abstract_match > unrelated
    assert unrelated == 0


def test_external_paper_search_is_requested_explicitly():
    question = (
        "Pull up a paper where SimCLR is used for breast cancer detection and compare it "
        "with my uploaded notes."
    )
    assert _requests_external_papers(question)
    assert _paper_search_query(question) == "SimCLR breast cancer detection"
    assert not _requests_external_papers("Compare the papers I already saved")


def test_external_paper_search_uses_focused_query_and_small_result_set(monkeypatch):
    searches = []
    monkeypatch.setattr(
        assistant,
        "search_papers",
        lambda *args: searches.append(args) or [],
    )
    literature_db = SimpleNamespace(commit=lambda: None)

    assert _discover_external_papers(
        literature_db,
        (
            "Pull up a paper where SimCLR is used for breast cancer detection and compare it "
            "with my uploaded notes."
        ),
    ) == []
    assert searches == [("SimCLR breast cancer detection", "openalex", 3)]
