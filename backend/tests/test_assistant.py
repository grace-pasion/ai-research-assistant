from app.services.assistant import _paper_relevance


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
