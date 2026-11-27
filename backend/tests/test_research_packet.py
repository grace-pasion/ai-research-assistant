import asyncio
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    Author,
    Conversation,
    Document,
    DocumentChunk,
    Message,
    MessageChunkSource,
    MessagePaperSource,
    Paper,
    PaperAuthor,
    PaperScreeningAssignment,
    PaperScreeningDecision,
    PaperStudyExtraction,
    ProjectInvitation,
    ProjectPaper,
    ResearchProject,
    TeamWorkspace,
    User,
)
from app.routers.project_exports import (
    export_research_packet,
    list_research_packet_assistant_outputs,
)
from app.schemas import ResearchPacketRequest


@pytest.fixture
def packet_databases(tmp_path):
    research_engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
    literature_engine = create_engine(f"sqlite:///{tmp_path / 'literature.sqlite'}")
    research_models = (
        User,
        TeamWorkspace,
        ResearchProject,
        ProjectInvitation,
        ProjectPaper,
        PaperScreeningDecision,
        PaperScreeningAssignment,
        PaperStudyExtraction,
        Annotation,
        Document,
        DocumentChunk,
        Conversation,
        Message,
        MessageChunkSource,
        MessagePaperSource,
    )
    for model in research_models:
        model.__table__.create(research_engine)
    for model in (Paper, Author, PaperAuthor):
        model.__table__.create(literature_engine)

    with Session(research_engine) as db, Session(literature_engine) as literature_db:
        owner = User(email="owner@example.com", name="Owner", password_hash="hashed")
        other_user = User(email="other@example.com", name="Other", password_hash="hashed")
        db.add_all((owner, other_user))
        db.flush()
        project = ResearchProject(user_id=owner.user_id, project_name="Packet project")
        other_project = ResearchProject(user_id=owner.user_id, project_name="Other project")
        db.add_all((project, other_project))
        db.flush()

        document = Document(
            project_id=project.project_id,
            filename="trial-notes.pdf",
            file_type="pdf",
            storage_path="test/trial-notes.pdf",
            file_size=20,
            processing_status="ready",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id=document.document_id,
            chunk_index=0,
            chunk_text="The trial found a modest improvement.",
            page_number=4,
            token_count=7,
        )
        db.add(chunk)

        paper = Paper(
            external_paper_id="paper-1",
            api_provider="crossref",
            title="A trial of the intervention",
            abstract="The intervention improved outcomes.",
            publication_year=2024,
            doi="10.1234/packet",
            paper_url="https://doi.org/10.1234/packet",
            venue="Journal of Packet Research",
        )
        other_paper = Paper(
            external_paper_id="paper-2",
            api_provider="crossref",
            title="A paper outside the project",
            publication_year=2022,
        )
        literature_db.add_all((paper, other_paper))
        literature_db.flush()
        author = Author(
            author_name="Jane Researcher",
            external_author_id="author-1",
            api_provider="crossref",
        )
        literature_db.add(author)
        literature_db.flush()
        literature_db.add(
            PaperAuthor(paper_id=paper.paper_id, author_id=author.author_id, author_order=0)
        )
        db.add(ProjectPaper(project_id=project.project_id, paper_id=paper.paper_id))
        db.add(ProjectPaper(project_id=other_project.project_id, paper_id=other_paper.paper_id))

        note = Annotation(
            project_id=project.project_id,
            paper_id=paper.paper_id,
            created_by=owner.user_id,
            quote="The intervention improved outcomes.",
            note="Check the follow-up period.",
            tags=["methods"],
            is_pinned=True,
        )
        unselected_note = Annotation(
            project_id=project.project_id,
            document_id=document.document_id,
            created_by=owner.user_id,
            note="Do not include this note.",
        )
        db.add_all((note, unselected_note))

        conversation = Conversation(
            user_id=owner.user_id,
            project_id=project.project_id,
            title="Intervention findings",
        )
        private_conversation = Conversation(
            user_id=other_user.user_id,
            project_id=project.project_id,
            title="Private collaborator response",
        )
        db.add_all((conversation, private_conversation))
        db.flush()
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        question = Message(
            conversation_id=conversation.conversation_id,
            role="user",
            content="What did the intervention change?",
            reviewed=True,
            created_at=base_time,
        )
        approved = Message(
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="The trial found a modest improvement [S1]. The paper reports better outcomes [S2].",
            reviewed=True,
            approval_id="approved-output",
            created_at=base_time + timedelta(microseconds=1),
        )
        unapproved = Message(
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="This draft must not be exported.",
            reviewed=False,
            created_at=base_time + timedelta(seconds=1),
        )
        private_output = Message(
            conversation_id=private_conversation.conversation_id,
            role="assistant",
            content="A collaborator's private answer.",
            reviewed=True,
            approval_id="private-approved-output",
            created_at=base_time + timedelta(seconds=2),
        )
        db.add_all((question, approved, unapproved, private_output))
        db.flush()
        db.add_all(
            (
                MessageChunkSource(
                    message_id=approved.message_id,
                    chunk_id=chunk.chunk_id,
                    source_order=0,
                ),
                MessagePaperSource(
                    message_id=approved.message_id,
                    paper_id=paper.paper_id,
                    source_order=1,
                ),
            )
        )
        db.commit()
        literature_db.commit()
        yield {
            "db": db,
            "literature_db": literature_db,
            "owner": owner,
            "other_user": other_user,
            "project": project,
            "paper": paper,
            "other_paper": other_paper,
            "note": note,
            "unselected_note": unselected_note,
            "conversation": conversation,
            "approved": approved,
            "unapproved": unapproved,
            "private_output": private_output,
        }

    research_engine.dispose()
    literature_engine.dispose()


def _read_archive(response) -> zipfile.ZipFile:
    async def read_body():
        return b"".join([chunk async for chunk in response.body_iterator])

    return zipfile.ZipFile(BytesIO(asyncio.run(read_body())))


def test_packet_output_options_only_list_requesters_approved_responses(packet_databases):
    data = packet_databases
    outputs = list_research_packet_assistant_outputs(
        data["project"].project_id,
        data["db"],
        data["owner"],
    )

    assert [item.message_id for item in outputs] == [data["approved"].message_id]
    assert outputs[0].conversation_title == "Intervention findings"
    assert "modest improvement" in outputs[0].excerpt


def test_research_packet_contains_selected_notes_papers_and_cited_approved_output(packet_databases):
    data = packet_databases
    response = export_research_packet(
        data["project"].project_id,
        ResearchPacketRequest(
            paper_ids=[data["paper"].paper_id],
            annotation_ids=[data["note"].annotation_id],
            assistant_message_ids=[data["approved"].message_id],
        ),
        data["db"],
        data["literature_db"],
        data["owner"],
    )
    archive = _read_archive(response)

    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="research-packet.zip"'
    assert {
        "README.txt",
        "manifest.json",
        "papers/papers.json",
        "papers/notes.json",
        "references/references.ris",
        "references/references.bib",
        "assistant/approved-outputs.json",
        f"assistant/approved-outputs/{data['approved'].message_id}.md",
    }.issubset(set(archive.namelist()))

    manifest = json.loads(archive.read("manifest.json"))
    papers = json.loads(archive.read("papers/papers.json"))
    notes = json.loads(archive.read("papers/notes.json"))
    outputs = json.loads(archive.read("assistant/approved-outputs.json"))
    markdown = archive.read(
        f"assistant/approved-outputs/{data['approved'].message_id}.md"
    ).decode()

    assert manifest["paper_count"] == 1
    assert manifest["note_count"] == 1
    assert manifest["approved_output_count"] == 1
    assert manifest["citation_count"] == 2
    assert papers[0]["title"] == "A trial of the intervention"
    assert "Jane Researcher" in papers[0]["authors"]
    assert notes[0]["note"] == "Check the follow-up period."
    assert notes[0]["is_pinned"] is True
    assert "Do not include this note." not in archive.read("papers/notes.json").decode()
    assert outputs[0]["approved"] is True
    assert outputs[0]["question"] == "What did the intervention change?"
    assert [source["citation"] for source in outputs[0]["citations"]] == ["[S1]", "[S2]"]
    assert outputs[0]["citations"][0]["page_number"] == 4
    assert outputs[0]["citations"][1]["doi"] == "10.1234/packet"
    assert "This draft must not be exported." not in markdown
    assert "[S1]" in markdown and "[S2]" in markdown
    assert "Jane Researcher" in archive.read("references/references.bib").decode()


def test_research_packet_includes_references_for_cited_papers(packet_databases):
    data = packet_databases
    response = export_research_packet(
        data["project"].project_id,
        ResearchPacketRequest(assistant_message_ids=[data["approved"].message_id]),
        data["db"],
        data["literature_db"],
        data["owner"],
    )
    archive = _read_archive(response)

    papers = json.loads(archive.read("papers/papers.json"))
    references = archive.read("references/references.ris").decode()

    assert [paper["title"] for paper in papers] == ["A trial of the intervention"]
    assert "A trial of the intervention" in references
    assert "10.1234/packet" in references


def test_research_packet_rejects_unavailable_or_other_users_private_items(packet_databases):
    data = packet_databases

    with pytest.raises(HTTPException) as unavailable_paper:
        export_research_packet(
            data["project"].project_id,
            ResearchPacketRequest(paper_ids=[data["other_paper"].paper_id]),
            data["db"],
            data["literature_db"],
            data["owner"],
        )
    assert unavailable_paper.value.status_code == 404

    with pytest.raises(HTTPException) as unapproved_output:
        export_research_packet(
            data["project"].project_id,
            ResearchPacketRequest(assistant_message_ids=[data["unapproved"].message_id]),
            data["db"],
            data["literature_db"],
            data["owner"],
        )
    assert unapproved_output.value.status_code == 404

    with pytest.raises(HTTPException) as private_output:
        export_research_packet(
            data["project"].project_id,
            ResearchPacketRequest(assistant_message_ids=[data["private_output"].message_id]),
            data["db"],
            data["literature_db"],
            data["owner"],
        )
    assert private_output.value.status_code == 404


def test_research_packet_request_requires_unique_nonempty_selection(packet_databases):
    with pytest.raises(ValueError, match="Select at least one"):
        ResearchPacketRequest()

    paper_id = uuid.uuid4()
    with pytest.raises(ValueError, match="must not contain duplicates"):
        ResearchPacketRequest(paper_ids=[paper_id, paper_id])
    with pytest.raises(ValidationError):
        ResearchPacketRequest(paper_ids=[uuid.uuid4() for _ in range(101)])
