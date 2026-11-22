# Fieldnotes — AI Research Assistant

Fieldnotes is a local-first research workspace for organizing research projects and files, searching scholarly papers, and asking questions grounded in your sources. The web client is React + TypeScript; the API is FastAPI; PostgreSQL stores user research and shared literature in separate databases, with pgvector for document embeddings.

## What is implemented

- Account registration, login, signed bearer tokens, and per-user project ownership.
- Account and project data persist in PostgreSQL across logout/login and normal Docker restarts; logging out clears the local session token, not the account.
- Research project create/list/update/delete, private document storage, and project-level document text search.
- PDF, DOCX, TXT, and Markdown upload and extraction. Scanned PDF pages are processed with Tesseract OCR. Files are limited to 25 MB by default and PDFs to 100 pages.
- Document chunking and OpenAI embeddings, stored in pgvector.
- OpenAlex and Crossref literature search, cached paper and author metadata, query history, and saving/removing papers from projects.
- Project conversations with question, comparison, and research-direction modes. Retrieval combines relevant document chunks and saved-paper abstracts.
- A mandatory human approval step: generated answers and conversation messages are not saved until **Approve & save** is clicked. Draft approval tokens are signed, user/project-bound, expire after 15 minutes, and are idempotent.
- Docker Compose setup, API health endpoint, interactive API docs, and focused backend tests.

## Run locally with Docker

You need Docker Desktop with Docker Compose enabled. From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` before starting:

1. Replace `POSTGRES_PASSWORD` and `JWT_SECRET` with private random values. Use letters and digits only for `POSTGRES_PASSWORD` (for example, generate a hex value with `python -c "import secrets; print(secrets.token_hex(32))"`); the password is included in a database URL.
2. Set `OPENAI_API_KEY` to your own OpenAI API key. Keep it in `.env`; **do not paste it into chat or commit it**. OpenAI usage may incur charges.
3. Optionally set `OPENALEX_EMAIL` to identify polite OpenAlex API requests.

Then start the stack:

```powershell
docker compose up --build
```

Open the app at <http://localhost:5173>. The API health check is at <http://localhost:8000/api/health>, and interactive API documentation is at <http://localhost:8000/docs>.

Create an account in the app. Add a research project, upload documents, and search OpenAlex or Crossref for papers. OpenAI is required for semantic document embeddings and assistant answers. Without an OpenAI key, uploads are retained and text can still be searched; documents show **Needs API key** and can be reprocessed after you add a key and restart the API. Academic paper search does not need an OpenAI key.

The database and uploaded files persist in Docker volumes. To stop the app, press `Ctrl+C`; to start it again, run `docker compose up`. To permanently erase all local research data, explicitly remove the named volumes with `docker compose down --volumes` (this is destructive).

## GitHub Pages deployment

GitHub Pages hosts only the static React frontend; it does not run the FastAPI backend, PostgreSQL, or uploaded-file storage. The included workflow builds and publishes the frontend on pushes to `main` and on manual runs. For a no-cost demo, the API can run on Render Free, with Supabase Free PostgreSQL and a private Storage bucket. This is not a production hosting setup: both providers impose limits, and Render's free service sleeps when idle.

If `VITE_API_URL` is not set, the workflow still tests and builds the frontend, but warns and skips deployment. Set the variable and run the workflow again to publish.

### 1. Create Supabase database and private file bucket

1. Create a Supabase project on its Free plan. Keep the database password private.
2. In **Storage**, create a bucket named `research-documents` and leave it **private**.
3. In **Project Settings → API Keys**, copy the project URL and a **Secret key** beginning with `sb_secret_`. The secret key is privileged: enter it only in Render's backend environment variables; never put it in GitHub variables or frontend code. The backend also accepts the legacy `service_role` key if your project only provides that.
4. Open **Connect** in the project dashboard and copy the **Session pooler** PostgreSQL connection string. Use the pooler rather than the direct database connection for Render's IPv4 network. Its database name should be `postgres`.

### 2. Deploy the API on Render

1. In Render, choose **New → Blueprint**, connect `grace-pasion/ai-research-assistant`, and deploy the repository's `render.yaml`.
2. When prompted, enter the Supabase session-pooler connection string as `DATABASE_URL`, the Supabase project URL as `SUPABASE_URL`, and the `sb_secret_...` key as `SUPABASE_SECRET_KEY`. Enter your OpenAI API key as `OPENAI_API_KEY` if you want embeddings and AI answers; this key is optional for accounts, projects, file text extraction, and academic search. Do not send secrets in chat or commit them.
3. Render generates a private `JWT_SECRET` for the backend. Leave `STORAGE_BACKEND=supabase`, `SUPABASE_STORAGE_BUCKET=research-documents`, and `CORS_ORIGINS=https://grace-pasion.github.io` as configured by the blueprint. Do not add a Render disk; Supabase Storage is the persistent file store.
4. Wait for the deployment to finish, then open `https://<your-render-service>.onrender.com/api/health`. A healthy service returns `{"status":"ok"}`.

The same Supabase database stores the application's research and literature tables; `LITERATURE_DATABASE_URL` automatically falls back to `DATABASE_URL`. The API creates its tables and enables the `vector` extension on first startup.

### 3. Connect GitHub Pages to the API

1. In the GitHub repository, open **Settings → Secrets and variables → Actions → Variables**, then create the repository variable `VITE_API_URL` with the Render service's public HTTPS base URL, such as `https://fieldnotes-api.onrender.com`. Do not add `/api` or a trailing slash. This URL is public configuration; never put API keys or database credentials here.
2. Open **Settings → Pages** and choose **GitHub Actions** as the build and deployment source.
3. Push the changes to `main` (or run **Deploy frontend to GitHub Pages** from **Actions**). Check the workflow result and visit <https://grace-pasion.github.io/ai-research-assistant/>.

Render Free services sleep after 15 minutes without traffic and can take time to wake up. Supabase Free projects may pause after a period of inactivity and have storage/database quotas. Free plans do not provide production uptime guarantees or a reliable backup plan; do not store the only copy of important research there. Check each provider's current limits before deploying.

## Human review and data writes

Generating an assistant response only reads your project data and calls OpenAI; it does not save a conversation or message. Inspect the proposed response and cited sources, then select **Approve & save** to store both the question and answer with their source references. **Discard** leaves no conversation data behind. Saving papers, uploading/deleting files, and editing/deleting projects are direct user actions and take effect immediately.

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
- The first PostgreSQL container start creates `research_db` and `literature_db`; the API creates tables and pgvector indexes on startup. The database initialization script only runs for a new Postgres data volume.
