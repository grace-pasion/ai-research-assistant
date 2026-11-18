# AI Research Assistant

> **Project snapshot — November 17, 2026**<br>
> An initial plan for a web app that helps researchers keep their materials together, find relevant academic work, and explore a topic with AI.

## Purpose and goals

Research often means juggling PDFs, search results, and notes across different tools. This project aims to bring those tasks into one workspace:

- **Organize research:** upload documents and group them into research projects.
- **Discover literature:** search academic sources and save useful papers.
- **Ask grounded questions:** get answers based on uploaded documents and papers, with sources to follow up on.
- **Explore a topic:** compare literature and surface possible research gaps or next directions.

**First milestone:** a usable web-app prototype for managing documents, searching papers, and asking source-backed questions. The diagrams and feature scope below are initial sketches and may change as the project develops.

## Initial data model

The sketch separates user-owned research data from reusable academic literature metadata. They may be logical schemas in one PostgreSQL deployment; the physical database setup is still to be decided.

```mermaid
erDiagram
    USER ||--o{ RESEARCH_PROJECT : owns
    RESEARCH_PROJECT ||--o{ DOCUMENT : contains
    RESEARCH_PROJECT ||--o{ CONVERSATION : has
    RESEARCH_PROJECT ||--o{ SEARCH_QUERY : starts
    CONVERSATION ||--o{ MESSAGE : contains
    DOCUMENT ||--o{ DOCUMENT_CHUNK : split_into
    MESSAGE ||--o{ MESSAGE_CHUNK_SOURCE : cites
    DOCUMENT_CHUNK ||--o{ MESSAGE_CHUNK_SOURCE : cited_by
    MESSAGE ||--o{ MESSAGE_PAPER_SOURCE : cites
    PAPER ||--o{ MESSAGE_PAPER_SOURCE : cited_by
    SEARCH_QUERY ||--o{ SEARCH_QUERY_RESULT : returns
    PAPER ||--o{ SEARCH_QUERY_RESULT : appears_in
    RESEARCH_PROJECT ||--o{ PROJECT_PAPER : saves
    PAPER ||--o{ PROJECT_PAPER : saved_to
    DOCUMENT ||--o{ DOCUMENT_PAPER : related_to
    PAPER ||--o{ DOCUMENT_PAPER : relates_to
    PAPER ||--o{ PAPER_AUTHOR : has
    AUTHOR ||--o{ PAPER_AUTHOR : writes

    USER {
        uuid user_id PK
        string email
        string name
    }
    RESEARCH_PROJECT {
        uuid project_id PK
        uuid user_id FK
        string project_name
        text description
    }
    DOCUMENT {
        uuid document_id PK
        uuid project_id FK
        string filename
        string file_type
        text storage_path
        string processing_status
    }
    DOCUMENT_CHUNK {
        uuid chunk_id PK
        uuid document_id FK
        int chunk_index
        text chunk_text
        vector embedding
    }
    CONVERSATION {
        uuid conversation_id PK
        uuid project_id FK
        string title
    }
    MESSAGE {
        uuid message_id PK
        uuid conversation_id FK
        string role
        text content
    }
    MESSAGE_CHUNK_SOURCE {
        uuid message_id PK, FK
        uuid chunk_id PK, FK
    }
    MESSAGE_PAPER_SOURCE {
        uuid message_id PK, FK
        uuid paper_id PK, FK
    }
    SEARCH_QUERY {
        uuid query_id PK
        uuid project_id FK
        text query_text
        string api_provider
    }
    SEARCH_QUERY_RESULT {
        uuid query_id PK, FK
        uuid paper_id PK, FK
        float relevance_score
    }
    PROJECT_PAPER {
        uuid project_id PK, FK
        uuid paper_id PK, FK
        string relationship_type
    }
    DOCUMENT_PAPER {
        uuid document_id PK, FK
        uuid paper_id PK, FK
        float relevance_score
    }
    PAPER {
        uuid paper_id PK
        string external_paper_id
        string api_provider
        text title
        text abstract
        int publication_year
        string doi
        string paper_url
    }
    PAPER_AUTHOR {
        uuid paper_id PK, FK
        uuid author_id PK, FK
        int author_order
    }
    AUTHOR {
        uuid author_id PK
        string author_name
        string external_author_id
    }
```

## Rough system design

The stack follows the initial proposal: React, Python/FastAPI, PostgreSQL with pgvector, academic search APIs, and an LLM API. Redis/Celery is shown as an option for slower document-processing jobs.

```mermaid
flowchart LR
    R[Researcher] -->|uses| UI[React web app]
    UI -->|authenticated requests| API[Python / FastAPI]
    API --> AUTH[Authentication and project access]
    API -->|upload| PROC[Document processing]
    PROC --> EXTRACT[PDF and text extraction]
    EXTRACT --> CHUNK[Chunking and embeddings]
    CHUNK -->|document metadata and chunks| DB[(PostgreSQL + pgvector)]
    PROC -. optional background jobs .-> JOBS[Redis + Celery]
    API -->|search request| SEARCH[Academic search service]
    SEARCH -->|metadata lookup| EXT[OpenAlex / Crossref / Semantic Scholar]
    EXT -->|paper metadata| DB
    API -->|retrieve relevant chunks and papers| DB
    DB -->|context and sources| RAG[RAG context builder]
    RAG -->|prompt| LLM[OpenAI API]
    LLM -->|answer| API
    API -->|answer and citations| UI
```

**Typical question flow:** the user asks a question in the web app; the API checks access, retrieves relevant document chunks and saved papers, sends grounded context to the LLM, and returns an answer with sources.

## Initial daily goals

An initial **10-work-session** sequence, sized for roughly **30–40 project hours**. Follow it across the remaining class days; combine sessions if the course calendar is shorter.

| Day | Goal |
|---|---|
| 1 | Confirm the minimum viable feature set, user flow, and technology choices. |
| 2 | Set up the app skeleton and initial PostgreSQL schema. |
| 3 | Build research-project and document upload/listing flows. |
| 4 | Extract document text; add chunking and embedding storage. |
| 5 | Integrate one academic search provider and save paper metadata. |
| 6 | Retrieve relevant document chunks and papers for a question. |
| 7 | Generate answers with source references and retain conversation history. |
| 8 | Connect the main React screens to the API; refine the core user flow. |
| 9 | Test the end-to-end flow, handle errors, and fix the most important issues. |
| 10 | Prepare a demo, finish concise setup/use documentation, and identify next steps. |

## Optional UX sketch

```text
+----------------------+------------------------------------+
| Projects             | Project: Climate adaptation        |
|  + New project       |                                    |
|  Climate adaptation  | [Documents] [Papers] [Ask]          |
|  Other project       |                                    |
|                      | Ask about this research...           |
|                      | [________________________________]   |
|                      |                                    |
|                      | Answer with linked document and     |
|                      | paper sources                       |
+----------------------+------------------------------------+
```
