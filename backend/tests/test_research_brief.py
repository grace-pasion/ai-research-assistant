from datetime import datetime, timezone
from io import BytesIO

import pytest
from docx import Document as WordDocument
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Author,
    Conversation,
    Document,
    DocumentChunk,
    Message,
    MessageChunkSource,
    MessagePaperSource,
    Paper,
    PaperAuthor,
    ProjectInvitation,
    ResearchProject,
    TeamWorkspace,
    User,
)
from app.routers.assistant import export_research_brief
from app.services.research_brief import parse_evidence_matrix


@pytest.fixture
def brief_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    for model in (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        Conversation,
        Message,
        Document,
        DocumentChunk,
        MessageChunkSource,
        MessagePaperSource,
    ):
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        user = User(email="reader@example.com", name="Reader", password_hash="hashed")
        db.add(user)
        db.flush()
        project = ResearchProject(user_id=user.user_id, project_name="Evidence review")
        db.add(project)
        db.flush()
        conversation = Conversation(
            user_id=user.user_id,
            project_id=project.project_id,
            title="Effects of intervention",
        )
        db.add(conversation)
        db.flush()

        document = Document(
            project_id=project.project_id,
            filename="study.pdf",
            file_type="pdf",
            storage_path="test/study.pdf",
            file_size=100,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id=document.document_id,
            chunk_index=0,
            chunk_text="The study reports a significant improvement.",
            page_number=6,
            token_count=7,
        )
        db.add(chunk)

        paper = Paper(
            external_paper_id="paper-1",
            api_provider="crossref",
            title="A comparative trial",
            abstract="The trial reports a modest effect.",
            publication_year=2023,
            doi="10.1234/trial",
            paper_url="https://doi.org/10.1234/trial",
            venue="Journal of Example Studies",
        )
        literature_db.add(paper)
        literature_db.flush()
        author = Author(
            author_name="Jane Doe",
            external_author_id="author-1",
            api_provider="crossref",
        )
        literature_db.add(author)
        literature_db.flush()
        literature_db.add(
            PaperAuthor(paper_id=paper.paper_id, author_id=author.author_id, author_order=0)
        )
        literature_db.flush()

        question_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        question = Message(
            conversation_id=conversation.conversation_id,
            role="user",
            content="What evidence supports this intervention?",
            reviewed=True,
            created_at=question_time,
        )
        assistant = Message(
            conversation_id=conversation.conversation_id,
            role="assistant",
            content=(
                "| Source | Research question | Methods | Sampling | Findings | Limitations | Citations |\n"
                "|---|---|---|---|---|---|---|\n"
                "| study.pdf | Intervention effectiveness [S1] | [Missing evidence] | [Missing evidence] | "
                "The study reports a significant improvement. [S1] | [Missing evidence] | [S1] |\n"
                "| A comparative trial | Intervention effectiveness [S2] | Randomized trial [S2] | "
                "[Missing evidence] | The trial reports a modest effect. [S2] | [Missing evidence] | [S2] |"
            ),
            reviewed=True,
            created_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        )
        db.add_all([question, assistant])
        db.flush()
        db.add_all(
            [
                MessageChunkSource(
                    message_id=assistant.message_id,
                    chunk_id=chunk.chunk_id,
                    source_order=0,
                ),
                MessagePaperSource(
                    message_id=assistant.message_id,
                    paper_id=paper.paper_id,
                    source_order=1,
                ),
            ]
        )
        db.commit()
        literature_db.commit()
        yield db, literature_db, user, project, conversation, question, assistant

    research_engine.dispose()
    literature_engine.dispose()


def test_parse_evidence_matrix_requires_a_well_formed_matrix():
    with pytest.raises(ValueError, match="does not contain"):
        parse_evidence_matrix("- A cited claim [S1]")

    with pytest.raises(ValueError, match="malformed row"):
        parse_evidence_matrix(
            "| Source | Research question | Methods | Sampling | Findings | Limitations | Citations |\n"
            "|---|---|---|---|---|---|---|\n"
            "| Only a source |"
        )


def test_export_research_brief_contains_synthesis_matrix_and_bibliography(brief_databases):
    db, literature_db, user, project, conversation, _, assistant = brief_databases

    response = export_research_brief(
        project.project_id,
        conversation.conversation_id,
        assistant.message_id,
        db,
        literature_db,
        user,
    )
    document = WordDocument(BytesIO(response.body))
    paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)
    table_content = "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )

    assert response.media_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment; filename=\"research-brief.docx\"" == response.headers["content-disposition"]
    assert "Synthesis" in paragraphs
    assert "The study reports a significant improvement. [S1]" in paragraphs
    assert "Bibliography" in paragraphs
    assert "Jane Doe" in paragraphs
    assert "10.1234/trial" in paragraphs
    assert "study.pdf. Project document, PDF p. 6." in paragraphs
    assert "[Missing evidence]" in table_content
    assert "[S2]" in table_content


def test_export_requires_owned_approved_comparison(brief_databases):
    db, literature_db, user, project, conversation, _, assistant = brief_databases
    assistant.content = "A normal cited answer [S1]"
    db.commit()

    with pytest.raises(HTTPException) as not_a_comparison:
        export_research_brief(
            project.project_id,
            conversation.conversation_id,
            assistant.message_id,
            db,
            literature_db,
            user,
        )
    assert not_a_comparison.value.status_code == 409

    other_user = User(email="other@example.com", name="Other", password_hash="hashed")
    with pytest.raises(HTTPException) as not_owned:
        export_research_brief(
            project.project_id,
            conversation.conversation_id,
            assistant.message_id,
            db,
            literature_db,
            other_user,
        )
    assert not_owned.value.status_code == 404


def test_export_rejects_matrix_citations_without_a_source_record(brief_databases):
    db, literature_db, user, project, conversation, _, assistant = brief_databases
    assistant.content = assistant.content.replace("[S2]", "[S3]")
    db.commit()

    with pytest.raises(HTTPException) as unavailable_source:
        export_research_brief(
            project.project_id,
            conversation.conversation_id,
            assistant.message_id,
            db,
            literature_db,
            user,
        )

    assert unavailable_source.value.status_code == 409
