import uuid

import pytest
from pydantic import ValidationError

from app.schemas import AskRequest, SourceResponse


def test_source_response_allows_only_the_relevant_source_identifier():
    document_source = SourceResponse(
        kind="document",
        source_id=uuid.uuid4(),
        title="Notes.pdf",
        excerpt="A source excerpt.",
        document_id=uuid.uuid4(),
    )
    paper_source = SourceResponse(
        kind="paper",
        source_id=uuid.uuid4(),
        title="An article",
        excerpt="An abstract.",
        paper_id=uuid.uuid4(),
    )

    assert document_source.paper_id is None
    assert paper_source.document_id is None


def test_assistant_source_selection_requires_a_non_empty_selection():
    with pytest.raises(ValidationError):
        AskRequest(
            question="Summarize this study",
            source_selection={"document_ids": [], "paper_ids": []},
        )

    selected = AskRequest(
        question="Summarize this study",
        source_selection={
            "document_ids": [str(uuid.uuid4())],
            "paper_ids": [],
        },
    )
    assert selected.source_selection is not None
    assert len(selected.source_selection.document_ids) == 1
