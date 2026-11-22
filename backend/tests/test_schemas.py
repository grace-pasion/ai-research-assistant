import uuid

from app.schemas import SourceResponse


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
