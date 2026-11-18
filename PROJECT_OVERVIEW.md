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

The sketch separates user-owned research data from reusable academic literature metadata. Both may use PostgreSQL in one deployment; uploaded files live in separate local or cloud file storage.

```mermaid
erDiagram
    USER ||--o{ RESEARCH_PROJECT : owns
    USER ||--o{ CONVERSATION : creates
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
        uuid user_id FK
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
        string relationship_type
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

The stack follows the initial proposal: React, Python/FastAPI, PostgreSQL with pgvector, academic search APIs, and an LLM API. Original uploads go to local or cloud file storage; Tesseract OCR can extract text from scanned files. Redis/Celery is an option for slower document-processing jobs.

```mermaid
flowchart LR
    R[Researcher] -->|uses| UI[React web app]
    UI -->|authenticated requests| API[Python / FastAPI]
    API --> AUTH[Authentication and project access]
    API -->|original upload| FS[Local or cloud file storage]
    FS -->|file for processing| PROC[Document processing]
    PROC --> EXTRACT[PDF and text extraction]
    EXTRACT -. scanned files .-> OCR[Tesseract OCR]
    OCR --> CHUNK[Chunking and embeddings]
    EXTRACT --> CHUNK[Chunking and embeddings]
    CHUNK -->|document metadata and chunks| USERDB[(User Research DB - PostgreSQL + pgvector)]
    API -. optional background jobs .-> JOBS[Redis + Celery]
    JOBS -. queued work .-> PROC
    API -->|search request| SEARCH[Academic search service]
    SEARCH -->|metadata lookup| EXT[OpenAlex / Crossref / Semantic Scholar]
    EXT -->|paper metadata| LITDB[(Academic Literature DB - PostgreSQL)]
    API -->|retrieve document chunks| USERDB
    API -->|retrieve papers| LITDB
    USERDB -->|document context| RAG[RAG context builder]
    LITDB -->|paper context| RAG
    RAG -->|prompt| LLM[OpenAI API]
    LLM -->|answer| API
    API -->|answer and citations| UI
```

**Typical question flow:** the user asks a question in the web app; the API checks access, retrieves relevant document chunks and saved papers, sends grounded context to the LLM, and returns an answer with sources.

## Initial daily goals

Daily goals for **November 18–December 2, 2026** (15 days), at roughly **2–2.5 hours per day** or **30–40 project hours** total.

| Day | Goal |
|---|---|
| Nov 18 | Confirm the MVP, user flow, and technology choices; prepare the development environment. |
| Nov 19 | Set up the application skeleton and map the ERD into PostgreSQL tables. |
| Nov 20 | Implement the initial API and database connection; start the React app shell. |
| Nov 21 | Build research-project and document upload/listing flows; save files outside the database. |
| Nov 22 | Extract text from PDFs and text files; try OCR for scanned documents. |
| Nov 23 | Chunk extracted text, generate embeddings, and store/search them with pgvector. |
| Nov 24 | Integrate one academic search provider and save paper metadata and authors. |
| Nov 25 | Add search history and let users save relevant papers to a research project. |
| Nov 26 | Persist conversations and messages; retrieve relevant document and paper sources. |
| Nov 27 | Generate grounded AI answers and return citations to their sources. |
| Nov 28 | Connect the React project, documents, papers, and chat views to the API. |
| Nov 29 | Refine the core user flow and add background document processing if needed. |
| Nov 30 | Test the end-to-end flow, access controls, upload handling, and error states. |
| Dec 1 | Fix priority issues; prepare sample research data and a demo walkthrough. |
| Dec 2 | Demo the prototype, finish setup/use documentation, and capture next steps. |

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
