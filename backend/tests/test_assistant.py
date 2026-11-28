import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from openai import APIConnectionError
from sqlalchemy.exc import IntegrityError

import app.services.assistant as assistant
from app.routers import assistant as assistant_router
from app.schemas import AskRequest, RetryDraftRequest
from app.services.assistant import (
    _discover_external_papers,
    _paper_relevance,
    _paper_search_query,
    _requests_external_papers,
)


def test_openai_embedding_failure_is_reported_as_upstream_error(monkeypatch):
    def fail(**_kwargs):
        raise APIConnectionError(
            message="provider unavailable",
            request=httpx.Request("POST", "https://api.openai.com/v1/embeddings"),
        )

    monkeypatch.setattr(
        assistant,
        "_openai_client",
        lambda: SimpleNamespace(embeddings=SimpleNamespace(create=fail)),
    )
    monkeypatch.setattr(
        assistant,
        "get_settings",
        lambda: SimpleNamespace(openai_embedding_model="test-model"),
    )

    with pytest.raises(HTTPException) as error:
        assistant._retrieve_chunks(SimpleNamespace(scalar=lambda _query: uuid.uuid4()), uuid.uuid4(), "question")

    assert error.value.status_code == 502


def test_openai_answer_and_verifier_failures_are_reported_as_upstream_errors(monkeypatch):
    chunk = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_text="The study reports evidence.",
        page_number=None,
    )
    document = SimpleNamespace(document_id=chunk.document_id, filename="study.pdf")

    def fail(**_kwargs):
        raise APIConnectionError(
            message="provider unavailable",
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
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

    with pytest.raises(HTTPException) as answer_error:
        assistant.draft_answer(
            SimpleNamespace(),
            SimpleNamespace(),
            uuid.uuid4(),
            "What does the study report?",
            "question",
        )
    assert answer_error.value.status_code == 502

    with pytest.raises(HTTPException) as verifier_error:
        assistant._verify_evidence_claims(
            client,
            "test-model",
            "What does the study report?",
            [{"text": "The study reports evidence.", "evidence": [{"source_index": 1, "quote": "The study reports evidence."}]}],
            [{"title": "study.pdf", "page_number": None}],
        )
    assert verifier_error.value.status_code == 502


def test_concurrent_approval_conflict_returns_the_existing_approval(monkeypatch):
    expected = object()
    rollbacks = []

    def fail_commit():
        raise IntegrityError("insert", {}, Exception("duplicate approval"))

    monkeypatch.setattr(assistant_router, "_approved_response", lambda *_args: expected)
    result = assistant_router._commit_approval(
        SimpleNamespace(commit=fail_commit, rollback=lambda: rollbacks.append(True)),
        SimpleNamespace(),
        "approval-id",
        uuid.uuid4(),
        uuid.uuid4(),
    )

    assert result is expected
    assert rollbacks == [True]


def test_draft_retrieval_receives_only_selected_project_sources(monkeypatch):
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    user = SimpleNamespace(user_id=uuid.uuid4())
    draft_answer = lambda *args, **kwargs: ("Draft", [])
    received = {}

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDatabase:
        def __init__(self):
            self.results = [FakeResult([document_id]), FakeResult([paper_id])]

        def scalars(self, _query):
            return self.results.pop(0)

        def commit(self):
            pass

    class FakeSerializer:
        def dumps(self, _payload):
            return "signed-token"

    def capture_draft(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs
        return draft_answer(*args, **kwargs)

    monkeypatch.setattr(assistant_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "consume_daily_prompt", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "record_activity", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "draft_answer", capture_draft)
    monkeypatch.setattr(assistant_router, "_approval_serializer", FakeSerializer)
    payload = AskRequest(
        question="Summarize this study",
        source_selection={
            "document_ids": [str(document_id)],
            "paper_ids": [str(paper_id)],
        },
    )

    response = assistant_router.create_draft(
        project_id,
        payload,
        SimpleNamespace(),
        FakeDatabase(),
        SimpleNamespace(),
        user,
    )

    assert response.answer == "Draft"
    assert received["args"][2] == project_id
    assert received["kwargs"] == {
        "document_ids": {document_id},
        "paper_ids": {paper_id},
    }


def test_retry_draft_reuses_signed_question_mode_conversation_and_sources(monkeypatch):
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    retry_payload = {
        "user_id": str(user_id),
        "project_id": str(project_id),
        "question": "Compare the findings in these sources.",
        "mode": "compare",
        "conversation_id": str(conversation_id),
        "sources": [
            {"kind": "document", "id": str(chunk_id)},
            {"kind": "paper", "id": str(paper_id)},
        ],
    }
    new_sources = [
        {
            "kind": "document",
            "source_id": chunk_id,
            "title": "study.pdf",
            "excerpt": "The study reports an outcome.",
            "document_id": uuid.uuid4(),
            "page_number": 2,
        },
        {
            "kind": "paper",
            "source_id": paper_id,
            "title": "Saved paper",
            "excerpt": "The paper reports a second outcome.",
            "paper_id": paper_id,
        },
    ]
    received = {}
    dumped_payloads = []

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDatabase:
        def scalars(self, _query):
            return FakeResult([chunk_id])

        def commit(self):
            pass

    class FakeSerializer:
        def loads(self, token, max_age):
            assert token == "signed-review"
            assert max_age == 900
            return retry_payload

        def dumps(self, payload):
            dumped_payloads.append(payload)
            return "new-signed-review"

    def capture_draft(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs
        return "Another answer.", new_sources

    monkeypatch.setattr(assistant_router, "_approval_serializer", FakeSerializer)
    monkeypatch.setattr(
        assistant_router,
        "get_settings",
        lambda: SimpleNamespace(approval_token_max_age_seconds=900),
    )
    monkeypatch.setattr(assistant_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(
        assistant_router,
        "_conversation_for_user",
        lambda *_args: received.setdefault("conversation_checked", True),
    )
    monkeypatch.setattr(assistant_router, "consume_daily_prompt", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "record_activity", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "draft_answer", capture_draft)

    response = assistant_router.retry_draft(
        project_id,
        RetryDraftRequest(approval_token="signed-review"),
        SimpleNamespace(),
        FakeDatabase(),
        SimpleNamespace(scalars=lambda _query: FakeResult([paper_id])),
        SimpleNamespace(user_id=user_id),
    )

    assert response.answer == "Another answer."
    assert response.approval_token == "new-signed-review"
    assert received["args"][2:] == (
        project_id,
        "Compare the findings in these sources.",
        "compare",
        conversation_id,
    )
    assert received["kwargs"] == {
        "source_refs": [("document", chunk_id), ("paper", paper_id)],
    }
    assert received["conversation_checked"]
    assert dumped_payloads[0]["question"] == retry_payload["question"]
    assert dumped_payloads[0]["mode"] == retry_payload["mode"]
    assert dumped_payloads[0]["conversation_id"] == str(conversation_id)
    assert dumped_payloads[0]["sources"] == [
        {"kind": "document", "id": str(chunk_id)},
        {"kind": "paper", "id": str(paper_id)},
    ]


def test_retry_draft_rejects_sources_that_are_no_longer_available(monkeypatch):
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    retry_payload = {
        "user_id": str(user_id),
        "project_id": str(project_id),
        "question": "What does this document report?",
        "mode": "question",
        "conversation_id": None,
        "sources": [{"kind": "document", "id": str(chunk_id)}],
    }

    class FakeResult:
        def all(self):
            return []

    class FakeSerializer:
        def loads(self, _token, max_age):
            return retry_payload

    monkeypatch.setattr(assistant_router, "_approval_serializer", FakeSerializer)
    monkeypatch.setattr(
        assistant_router,
        "get_settings",
        lambda: SimpleNamespace(approval_token_max_age_seconds=900),
    )
    monkeypatch.setattr(assistant_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(
        assistant_router,
        "draft_answer",
        lambda *_args, **_kwargs: pytest.fail("Retry must not use a removed or unready source."),
    )

    with pytest.raises(HTTPException) as error:
        assistant_router.retry_draft(
            project_id,
            RetryDraftRequest(approval_token="signed-review"),
            SimpleNamespace(),
            SimpleNamespace(scalars=lambda _query: FakeResult()),
            SimpleNamespace(),
            SimpleNamespace(user_id=user_id),
        )

    assert error.value.status_code == 409


def test_retry_draft_rejects_a_token_from_another_user(monkeypatch):
    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        assistant_router,
        "_approval_serializer",
        lambda: SimpleNamespace(loads=lambda *_args, **_kwargs: {
            "user_id": str(uuid.uuid4()),
            "project_id": str(project_id),
        }),
    )
    monkeypatch.setattr(
        assistant_router,
        "get_settings",
        lambda: SimpleNamespace(approval_token_max_age_seconds=900),
    )

    with pytest.raises(HTTPException) as error:
        assistant_router.retry_draft(
            project_id,
            RetryDraftRequest(approval_token="other-user-token"),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(user_id=user_id),
        )

    assert error.value.status_code == 403


def test_draft_answer_retry_reuses_exact_document_chunks_and_papers(monkeypatch):
    excerpt = "The study reports a validated outcome measure."
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    paper_id = uuid.uuid4()
    chunk = SimpleNamespace(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_text=excerpt,
        page_number=3,
    )
    document = SimpleNamespace(document_id=document_id, filename="study.pdf")
    paper = SimpleNamespace(
        paper_id=paper_id,
        title="Methods paper",
        abstract="The paper reports a different outcome measure.",
        publication_year=None,
        paper_url="https://example.com/paper",
    )
    responses = iter(
        [
            json.dumps(
                {
                    "claims": [
                        {
                            "text": "The study reports a validated outcome measure.",
                            "evidence": [{"source_index": 1, "quote": excerpt}],
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "question_fully_answered": True,
                    "decisions": [{"claim_index": 1, "supported": True}],
                }
            ),
        ]
    )
    received = {}

    class FakeResult:
        def all(self):
            return []

    class FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))]
            )

    def retrieve_retry_chunks(_db, _project_id, ids):
        received["chunk_ids"] = ids
        return [(chunk, document)]

    def retrieve_retry_papers(_db, ids):
        received["paper_ids"] = ids
        return [{"paper": paper, "author_ids": []}]

    monkeypatch.setattr(
        assistant,
        "_openai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    monkeypatch.setattr(assistant, "_retrieve_retry_chunks", retrieve_retry_chunks)
    monkeypatch.setattr(assistant, "_retrieve_retry_papers", retrieve_retry_papers)
    monkeypatch.setattr(
        assistant,
        "_retrieve_chunks",
        lambda *_args, **_kwargs: pytest.fail("Retry must not search for new document chunks."),
    )
    monkeypatch.setattr(
        assistant,
        "_retrieve_papers",
        lambda *_args, **_kwargs: pytest.fail("Retry must not search for new saved papers."),
    )
    monkeypatch.setattr(
        assistant,
        "_discover_external_papers",
        lambda *_args, **_kwargs: pytest.fail("Retry must not discover new papers."),
    )
    monkeypatch.setattr(assistant, "get_settings", lambda: SimpleNamespace(openai_model="test-model"))

    answer, sources = assistant.draft_answer(
        SimpleNamespace(scalars=lambda _query: FakeResult()),
        SimpleNamespace(scalars=lambda _query: FakeResult()),
        uuid.uuid4(),
        "What does the study report?",
        "question",
        source_refs=[("document", chunk_id), ("paper", paper_id)],
    )

    assert answer.endswith("- The study reports a validated outcome measure. [S1]")
    assert received == {"chunk_ids": [chunk_id], "paper_ids": [paper_id]}
    assert [source["source_id"] for source in sources] == [chunk_id, paper_id]


def test_draft_answer_retry_stops_if_a_source_disappears_during_retrieval(monkeypatch):
    chunk_id = uuid.uuid4()
    monkeypatch.setattr(assistant, "_openai_client", lambda: SimpleNamespace())
    monkeypatch.setattr(assistant, "_retrieve_retry_chunks", lambda *_args: [])
    monkeypatch.setattr(assistant, "_retrieve_retry_papers", lambda *_args: [])

    with pytest.raises(HTTPException) as error:
        assistant.draft_answer(
            SimpleNamespace(),
            SimpleNamespace(),
            uuid.uuid4(),
            "What does this document report?",
            "question",
            source_refs=[("document", chunk_id)],
        )

    assert error.value.status_code == 409


def test_draft_rejects_sources_outside_the_project_before_retrieval(monkeypatch):
    project_id = uuid.uuid4()
    selected_id = uuid.uuid4()
    draft_answer = SimpleNamespace(called=False)

    class FakeResult:
        def all(self):
            return []

    class FakeDatabase:
        def scalars(self, _query):
            return FakeResult()

    def reject_if_called(*_args, **_kwargs):
        draft_answer.called = True
        raise AssertionError("Retrieval must not run for an unavailable source.")

    monkeypatch.setattr(assistant_router, "require_project_access", lambda *_args: None)
    monkeypatch.setattr(assistant_router, "draft_answer", reject_if_called)
    payload = AskRequest(
        question="Summarize this study",
        source_selection={"document_ids": [str(selected_id)], "paper_ids": []},
    )

    with pytest.raises(HTTPException) as error:
        assistant_router.create_draft(
            project_id,
            payload,
            SimpleNamespace(),
            FakeDatabase(),
            SimpleNamespace(),
            SimpleNamespace(user_id=uuid.uuid4()),
        )

    assert error.value.status_code == 422
    assert not draft_answer.called


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
    assert "<researcher_notes>" in provider_calls[0]["messages"][0]["content"]
    assert "not instructions or evidence" in provider_calls[0]["messages"][0]["content"]
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


def test_comparison_draft_builds_matrix_and_flags_unreported_fields(monkeypatch):
    excerpt = "The study surveyed 120 teachers using a five-point questionnaire."
    chunk = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_text=excerpt,
        page_number=2,
    )
    document = SimpleNamespace(document_id=chunk.document_id, filename="teacher-study.pdf")
    provider_calls = []
    responses = iter(
        [
            json.dumps(
                {
                    "rows": [
                        {
                            "source_index": 1,
                            "cells": {
                                "research_question": [
                                    {
                                        "text": "The study examined teachers' views.",
                                        "evidence": [{"source_index": 1, "quote": excerpt}],
                                    }
                                ],
                                "methods": [
                                    {
                                        "text": "The study used a questionnaire.",
                                        "evidence": [{"source_index": 1, "quote": excerpt}],
                                    }
                                ],
                                "sampling": [],
                                "findings": [],
                                "limitations": [],
                            },
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "question_fully_answered": False,
                    "decisions": [
                        {"claim_index": 1, "supported": True},
                        {"claim_index": 2, "supported": True},
                    ],
                }
            ),
        ]
    )

    class FakeCompletions:
        def create(self, **kwargs):
            provider_calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))]
            )

    monkeypatch.setattr(
        assistant,
        "_openai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
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
        "Compare the study's research design and findings.",
        "compare",
    )

    assert answer.startswith(
        "| Source | Research question | Methods | Sampling | Findings | Limitations | Citations |"
    )
    assert "The study examined teachers' views. [S1]" in answer
    assert "The study used a questionnaire. [S1]" in answer
    assert answer.count("[Missing evidence]") == 3
    assert answer.endswith("| [S1] |")
    assert sources[0]["title"] == "teacher-study.pdf"
    assert "research_question" in provider_calls[0]["messages"][0]["content"]
    assert "not instructions or evidence" in provider_calls[0]["messages"][0]["content"]


def test_comparison_claims_cannot_cite_a_different_source_row():
    sources = [
        {"title": "first.pdf", "excerpt": "The first report examined outcomes in a regional sample."},
        {"title": "second.pdf", "excerpt": "The second report used a national randomized controlled trial."},
    ]
    content = json.dumps(
        {
            "rows": [
                {
                    "source_index": 1,
                    "cells": {
                        "findings": [
                            {
                                "text": "The first study used a national randomized controlled trial.",
                                "evidence": [
                                    {
                                        "source_index": 2,
                                        "quote": sources[1]["excerpt"],
                                    }
                                ],
                            }
                        ]
                    },
                },
                {
                    "source_index": 2,
                    "cells": {
                        "methods": [
                            {
                                "text": "The second report used a randomized controlled trial.",
                                "evidence": [
                                    {
                                        "source_index": 2,
                                        "quote": sources[1]["excerpt"],
                                    }
                                ],
                            }
                        ]
                    },
                },
            ]
        }
    )

    claims = assistant._parse_comparison_claims(content, sources)

    assert len(claims) == 1
    assert claims[0]["source_index"] == 2
    assert claims[0]["citations"] == [2]
    assert claims[0]["field"] == "methods"
