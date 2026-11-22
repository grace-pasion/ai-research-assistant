# Fieldnotes — AI Research Assistant

Fieldnotes is a local-first research workspace for organizing research projects and files, searching scholarly papers, and asking questions grounded in your sources. The web client is React + TypeScript; the API is FastAPI; PostgreSQL stores research and literature data, with pgvector for document embeddings. Local development uses separate research and literature databases; hosted deployments may use one database or separate URLs.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the implemented system architecture, integrations, API surface, data flows, and complete user feature inventory.

## What is implemented

- Account registration with 12+ character, common-password checks; login, signed bearer tokens, and per-user project ownership.
- Sign-in throttling: 5 attempts per IP/email pair and 30 attempts per IP in a 15-minute window, with hashed identifiers and automatic reset after successful sign-in.
- Account and project data persist in PostgreSQL across logout/login and normal Docker restarts; logging out clears the local session token, not the account.
- Document and saved-paper annotations are stored in the PostgreSQL `annotations` table, not browser storage or the original file. They remain available after logout/login and service restarts; deleting a document or project removes its annotations.
- Research project create/list/update/delete, private document storage, and project-level document text search.
- PDF, DOCX, TXT, and Markdown upload and extraction. Scanned PDF pages are processed with Tesseract OCR. Files are limited to 25 MB by default and PDFs to 100 pages.
- Open an uploaded document to read its extracted text and view its highlights and notes in the document reader. On saved papers, annotate the available abstract; notes persist across sessions.
- Document chunking and OpenAI embeddings, stored in pgvector.
- OpenAlex and Crossref literature search with semantic re-ranking of paper abstracts when an OpenAI key is configured, cached paper and author metadata, query history, and saving/removing papers from projects.
- Import open-access PDFs for saved literature papers. Imported papers use the existing extraction, chunking, and embedding pipeline so their full text can be read, searched, and queried with the assistant.
- Project literature screening: mark saved papers unread, undecided, include, or exclude, record an optional short reason, and track reviewed/unread/undecided totals. Undecided papers count as reviewed.
- Project conversations with question, comparison, and research-direction modes. Retrieval combines relevant document chunks and saved-paper abstracts; prompts asking to find a paper also search OpenAlex and show retrieved results as linked chat sources.
- Assistant drafts are limited to 20 prompts per client IP per UTC day. This caps question-answer requests, not document-embedding requests made during upload or reprocessing.
- Separate administrator sign-in with an allowlisted account, user/account summaries, metadata-only activity history, and permanent account deletion.
- A mandatory human approval step: generated answers and conversation messages are not saved until **Approve & save** is clicked. Draft approval tokens are signed, user/project-bound, expire after 15 minutes, and are idempotent.
- Docker Compose setup, API health endpoint, interactive API docs, and focused backend tests.
- API security headers, HTTPS-only HSTS, and non-cacheable API responses.

## Run locally with Docker

You need Docker Desktop with Docker Compose enabled. From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` before starting:

1. Replace `POSTGRES_PASSWORD` and `JWT_SECRET` with private random values. Use letters and digits only for `POSTGRES_PASSWORD` (for example, generate a hex value with `python -c "import secrets; print(secrets.token_hex(32))"`); the password is included in a database URL.
2. Set `OPENAI_API_KEY` to your own OpenAI API key. Keep it in `.env`; **do not paste it into chat or commit it**. OpenAI usage may incur charges.
3. Optionally set `OPENALEX_API_KEY` to use your OpenAlex account's higher API budget, and `OPENALEX_EMAIL` to identify polite requests. Keep the key in `.env`; do not paste it into chat or commit it.

Then start the stack:

```powershell
docker compose up --build
```

Open the app at <http://localhost:5173>. The API health check is at <http://localhost:8000/api/health>, and interactive API documentation is at <http://localhost:8000/docs>.

Create an account in the app. Add a research project, upload documents, and search OpenAlex or Crossref for papers. In **Literature**, save papers to the project, record an unread/undecided/include/exclude screening decision and optional short reason, and select **Extract full text** to import an available open-access PDF. Undecided papers count as reviewed but remain distinct from included and excluded papers. The imported PDF appears in Documents and, after processing, its text is available for document search and assistant questions. If no open-access PDF is available, upload a copy you have access to. Open a document from the Documents list to read its extracted text, highlight passages, and view or add notes in the reader; use **Annotate** on a saved paper to annotate its available abstract. Notes and screening decisions persist in the project database across sessions. OpenAI is required for semantic literature re-ranking, document embeddings, and assistant answers. Without an OpenAI key, academic search still returns provider-ranked results, uploads are retained, and document text can still be searched; documents show **Needs API key** and can be reprocessed after you add a key and restart the API. In chat, ask to find or pull up a paper to search OpenAlex and include relevant paper abstracts and links in the draft.

The database (including annotations) and uploaded files persist in Docker volumes. To stop the app, press `Ctrl+C`; to start it again, run `docker compose up`. To permanently erase all local research data, explicitly remove the named volumes with `docker compose down --volumes` (this is destructive).

## GitHub Pages deployment

GitHub Pages hosts only the static React frontend; it does not run the FastAPI backend, PostgreSQL, or uploaded-file storage. The included workflow builds and publishes the frontend on pushes to `main` and on manual runs. For a no-cost demo, the API can run on Render Free, with Supabase Free PostgreSQL and a private Storage bucket. This is not a production hosting setup: both providers impose limits, and Render's free service sleeps when idle.

The workflow uses the repository Actions variable `VITE_API_URL` when set; otherwise, it falls back to `https://fieldnotes-api-l1bc.onrender.com`. It tests and builds the frontend before publishing. Set the variable to override the fallback when using a different API host.

### 1. Create Supabase database and private file bucket

1. Create a Supabase project on its Free plan. Keep the database password private.
2. In **Storage**, create a bucket named `research-documents` and leave it **private**.
3. In **Project Settings → API Keys**, copy the project URL and a **Secret key** beginning with `sb_secret_`. The secret key is privileged: enter it only in Render's backend environment variables; never put it in GitHub variables or frontend code. The backend also accepts the legacy `service_role` key if your project only provides that.
4. Open **Connect** in the project dashboard and copy the **Session pooler** PostgreSQL connection string. Use the pooler rather than the direct database connection for Render's IPv4 network. Its database name should be `postgres`.

### 2. Deploy the API on Render

1. In Render, choose **New → Blueprint**, connect `grace-pasion/ai-research-assistant`, and deploy the repository's `render.yaml`.
2. When prompted, enter the Supabase session-pooler connection string as `DATABASE_URL`, the Supabase project URL as `SUPABASE_URL`, and the `sb_secret_...` key as `SUPABASE_SECRET_KEY`. Enter your OpenAI API key as `OPENAI_API_KEY` if you want embeddings and AI answers; this key is optional for accounts, projects, file text extraction, and academic search. Enter your OpenAlex API key as `OPENALEX_API_KEY` to use your account's higher OpenAlex API budget. Do not send secrets in chat or commit them.
3. Render generates a private `JWT_SECRET` for the backend. Leave `STORAGE_BACKEND=supabase`, `SUPABASE_STORAGE_BUCKET=research-documents`, and `CORS_ORIGINS=https://grace-pasion.github.io` as configured by the blueprint. Do not add a Render disk; Supabase Storage is the persistent file store.
4. Wait for the deployment to finish, then open `https://<your-render-service>.onrender.com/api/health`. A healthy service returns `{"status":"ok"}`.

The same Supabase database stores the application's research and literature tables; `LITERATURE_DATABASE_URL` automatically falls back to `DATABASE_URL`. The API creates its tables—including `annotations`—adds literature-screening columns to existing project-paper tables, and enables the `vector` extension on startup.

### 3. Connect GitHub Pages to the API

1. Optionally, in the GitHub repository, open **Settings → Secrets and variables → Actions → Variables**, then create the repository variable `VITE_API_URL` with the Render service's public HTTPS base URL, such as `https://fieldnotes-api-l1bc.onrender.com`. Do not add `/api` or a trailing slash. The workflow falls back to this Fieldnotes Render URL when the variable is absent. This URL is public configuration; never put API keys or database credentials here.
2. Open **Settings → Pages** and choose **GitHub Actions** as the build and deployment source.
3. Push the changes to `main` (or run **Deploy frontend to GitHub Pages** from **Actions**). Check the workflow result and visit <https://grace-pasion.github.io/ai-research-assistant/>.

Render Free services sleep after 15 minutes without traffic and can take time to wake up. Supabase Free projects may pause after a period of inactivity and have storage/database quotas. Free plans do not provide production uptime guarantees or a reliable backup plan; do not store the only copy of important research there. Check each provider's current limits before deploying.

## Administrator console

1. Create a normal Fieldnotes account for yourself if you do not already have one.
2. In Render, add `ADMIN_EMAILS` as a backend environment variable with the exact email address for that account. Multiple administrator emails can be comma-separated. Keep this setting on the backend; do not add it to GitHub Pages variables. Redeploy the API after changing the allowlist.
3. Open <https://grace-pasion.github.io/ai-research-assistant/?portal=admin> and sign in with that account's existing email and password. This is a separate admin portal, but it does not create a second password or public admin-registration flow. For local development, use `http://localhost:5173/?portal=admin` and set `ADMIN_EMAILS` in `.env`.
4. The dashboard lists account email, joined date, project/document/saved-paper/conversation counts, last recorded activity, and a paginated activity feed. Activity records contain action types and limited operational metadata only: document contents and names, search terms, assistant prompts, and answers are not recorded or displayed. Tracking starts after this version is deployed; previous actions are not backfilled.
5. **Delete** permanently removes the selected account, its projects and research data, activity history, and stored document files. The current administrator cannot delete their own account. If the API cannot remove the user's stored files, it returns an error and does not delete the account.

## Human review and data writes

Generating an assistant response only reads your project data and calls OpenAI; it does not save a conversation or message. Inspect the proposed response and cited sources, then select **Approve & save** to store both the question and answer with their source references. **Discard** leaves no conversation data behind. Saving papers, uploading/deleting files, and editing/deleting projects are direct user actions and take effect immediately.

## Built-in account protections

New registrations require a password of 12–128 characters; a small local denylist blocks common choices and passwords made of one repeated character. Sign-in attempts for both researcher and administrator login are limited to 5 per IP/email pair and 30 per IP per 15 minutes. A successful sign-in clears the matching counters. Rate-limit keys are HMAC-hashed with the backend JWT secret; no raw IP or email is stored in the counters. These controls do not change existing passwords. API responses include security headers, HTTPS responses enable HSTS, and `/api/` responses are marked `no-store`.

## Local development and tests

The easiest supported run path is Docker Compose because it provisions both PostgreSQL databases, pgvector, and Tesseract. If running services outside Docker, use Python 3.12+, Node.js 22+, PostgreSQL 16 with pgvector, and Tesseract on `PATH`; configure the URLs and keys from `.env.example`.

Backend tests:

```powershell
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
Set-Location backend
python -m pytest
```

Frontend production build (Node.js 22+):

```powershell
Set-Location frontend
npm install
npm run build
```

## Notes and limitations

- OpenAlex and Crossref are used instead of scraping Google Scholar. Search availability and metadata completeness depend on those public services.
- OCR is performed locally inside the API container. Local Python installs need the Tesseract executable installed separately.
- OpenAI API keys, database passwords, and JWT secrets are read only by the backend. The example secrets are for local setup only; do not expose this development configuration to the public internet.
- The first PostgreSQL container start creates `research_db` and `literature_db`; the API creates tables, including `annotations`, adds literature-screening columns to existing project-paper tables, and creates pgvector indexes on startup. The database initialization script only runs for a new Postgres data volume.
