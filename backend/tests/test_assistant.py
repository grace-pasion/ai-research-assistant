import json
import uuid
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


def test_draft_answer_only_returns_claims_with_verbatim_verified_evidence(monkeypatch):
    excerpt = "Table 1 reports an average of 82.1 and excludes the WNLI task."
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk = SimpleNamespace(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_text=excerpt,
        page_number=6,
    )
    document = SimpleNamespace(document_id=document_id, filename="study.pdf")
    responses = iter(
        [
            json.dumps(
                {
                    "claims": [
                        {
                            "text": "The reported table average is 82.1 and excludes WNLI.",
                            "evidence": [{"source_index": 1, "quote": excerpt}],
                        },
                        {
                            "text": "The official GLUE score is 82.1.",
                            "evidence": [{"source_index": 1, "quote": excerpt}],
                        },
                        {
                            "text": "The paper reports a 90.0 score.",
                            "evidence": [{"source_index": 1, "quote": "A made-up unsupported passage."}],
                        },
                    ]
                }
            ),
            json.dumps(
                {
                    "question_fully_answered": False,
                    "decisions": [
                        {"claim_index": 1, "supported": True},
                        {"claim_index": 2, "supported": False},
                    ]
                }
            ),
        ]
    )
    provider_calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            provider_calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=next(responses)),
                    )
                ]
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()),
    )
    monkeypatch.setattr(assistant, "_openai_client", lambda: client)
    monkeypatch.setattr(assistant, "_retrieve_chunks", lambda *_args: [(chunk, document)])
    monkeypatch.setattr(assistant, "_retrieve_papers", lambda *_args: [])
    monkeypatch.setattr(assistant, "_discover_external_papers", lambda *_args: [])
    monkeypatch.setattr(
        assistant,
        "get_settings",
        lambda: SimpleNamespace(openai_model="test-model"),
    )

    answer, sources = assistant.draft_answer(
        SimpleNamespace(),
        SimpleNamespace(),
        uuid.uuid4(),
        "What does the table report?",
        "question",
    )

    assert answer.startswith("The cited evidence supports only part of your question;")
    assert answer.endswith("- The reported table average is 82.1 and excludes WNLI. [S1]")
    assert "[S2]" not in answer
    assert sources[0]["page_number"] == 6
    assert len(provider_calls) == 2
    assert provider_calls[0]["response_format"] == {"type": "json_object"}
    assert provider_calls[1]["temperature"] == 0
    verification_claims = json.loads(provider_calls[1]["messages"][1]["content"])["claims"]
    assert len(verification_claims) == 2


def test_draft_answer_abstains_when_no_claim_has_a_matching_quote(monkeypatch):
    chunk = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_text="The paper reports a masked language modeling objective.",
        page_number=3,
    )
    document = SimpleNamespace(document_id=chunk.document_id, filename="study.pdf")
    provider_calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            provider_calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "claims": [
                                        {
                                            "text": "The paper reports a clinical trial.",
                                            "evidence": [
                                                {
                                                    "source_index": 1,
                                                    "quote": "The trial included 900 patients.",
                                                }
                                            ],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

    monkeypatch.setattr(
        assistant,
        "_openai_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions()),
        ),
    )
    monkeypatch.setattr(assistant, "_retrieve_chunks", lambda *_args: [(chunk, document)])
    monkeypatch.setattr(assistant, "_retrieve_papers", lambda *_args: [])
    monkeypatch.setattr(assistant, "_discover_external_papers", lambda *_args: [])
    monkeypatch.setattr(
        assistant,
        "get_settings",
        lambda: SimpleNamespace(openai_model="test-model"),
    )

    answer, _sources = assistant.draft_answer(
        SimpleNamespace(),
        SimpleNamespace(),
        uuid.uuid4(),
        "What trial did the paper describe?",
        "question",
    )

    assert answer.startswith("I couldn")
    assert "[S1]" not in answer
    assert len(provider_calls) == 1
