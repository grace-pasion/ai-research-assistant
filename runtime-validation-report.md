# Runtime Validation Report

**Generated**: 2026-11-22T14:46:56-07:00
**Target**: `C:\Users\grpas\Downloads\cs452-final-project`

## Summary

| Step | Status | Exit code | Details |
|---|---|---:|---|
| Startup | PASS | 0 | Docker Compose services started; `/api/health` returned 200 and the frontend returned 200. |
| Backend tests | PASS | 0 | 68 tests passed; one existing Starlette/httpx deprecation warning. |
| Frontend tests | PASS | 0 | 4 Vitest tests passed across 2 files. |
| Frontend build | PASS | 0 | TypeScript check and Vite production build succeeded. |
| Live API journeys | PASS | 0 | Auth, project, document, annotation, literature, LaTeX, and assistant flows exercised against PostgreSQL/pgvector and configured external services. |
| Browser E2E | PASS | 0 | Chromium exercised registration, project creation, LaTeX persistence, document upload/search, assistant review, and cited-evidence navigation. |

**Overall**: PASS for the critical journeys exercised below. This does not establish that every possible input or deployment configuration is bug-free; known gaps are listed separately.

## Environment

- Docker: **AVAILABLE**, server 29.8.2.
- Node.js: **AVAILABLE** in the isolated Playwright container, v26.13.1. Host Node.js was not required.
- Playwright: **AVAILABLE**, v1.65.1 with bundled Chromium.
- Infrastructure: **PRIMARY** — Docker Compose PostgreSQL 16/pgvector and the local API/web services.
- Browser tier: **PRIMARY** — Playwright in an isolated container. The integrated browser connection timed out; the container-based browser run succeeded.
- OpenAI and OpenAlex credentials were configured in the API container; their values were not exposed in the test output.

## Journeys exercised

1. Registered a unique disposable user, verified invalid credentials and unauthenticated access fail, then created, listed, updated, and deleted a project. A standard user received 403 from the administrator endpoint.
2. Saved and reloaded a LaTeX workspace. Uploaded a text file, waited for extraction/indexing, read and searched its text, downloaded the original, reprocessed it, and created/read/edited/deleted an annotation.
3. Queried both OpenAlex and Crossref, saved results, updated screening status, and created/read/deleted a paper annotation. Imported the known open-access BERT paper; extraction produced 33 chunks with page locators.
4. Uploaded a two-page PDF, verified page numbers 1 and 2, generated an answer supported by the second-page passage, approved it, and confirmed the saved conversation retained the page-2 citation.
5. In Chromium, exercised the rendered registration/project/LaTeX/document/assistant flow. The UI showed the supporting passage, approval state, saved conversation, and navigation from the citation to the document reader.

Test accounts, projects, and uploaded files were cleaned up. A final database query found zero temporary validation accounts.

## Issue fixed

Deleting a document while its in-process extraction task was running could make the task raise a stale SQLAlchemy object error after rollback. The task now checks whether the document row still exists and exits when the document was deleted. A regression test was added to `backend/tests/test_processing.py`; the behavior is documented in `ARCHITECTURE.md`.

## Test evidence

- Backend: `python -m pytest -p no:byu_pytest_utils` from `backend` — **68 passed**, exit code 0.
- Frontend: `docker compose run --build --rm web npm test` — **4 passed**, exit code 0.
- Build: `docker compose run --build --rm web npm run build` — exit code 0.
- Startup/readiness: `docker compose up --build -d`; `/api/health` → 200; frontend → 200.
- Browser: isolated Playwright 1.65.1/Chromium run — exit code 0. Its temporary runner and Compose override were removed after the run; normal Compose configuration was restored.

## Known gaps

- Supabase Storage was not exercised; runtime tests used local Docker storage.
- Scanned-PDF OCR was not tested end-to-end.
- Administrator login and privileged user/activity management were not exercised live because no administrator test credentials were available. The non-admin denial path was tested, and the existing administrator unit tests passed.
- The runtime browser run was a temporary multi-step harness rather than a checked-in Playwright suite.
