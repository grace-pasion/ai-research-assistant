from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import (
    ensure_annotation_synthesis_columns,
    ensure_document_chunk_page_column,
    ensure_library_metadata_columns,
    ensure_notification_details_column,
    ensure_project_collaboration_columns,
    ensure_project_paper_screening_columns,
    ensure_project_team_workspace_column,
    ensure_python_artifact_provenance_columns,
    ensure_python_artifact_run_columns,
    ensure_python_workspace_files_column,
    ensure_search_query_reproducibility_columns,
    ensure_user_profile_picture_column,
    ensure_user_username_column,
    initialize_database,
    make_engine,
)
from app.models import LiteratureBase, ResearchBase
from app.routers import (
    admin,
    annotations,
    assistant,
    auth,
    collections,
    collaboration,
    documents,
    latex,
    notifications,
    papers,
    project_home,
    project_exports,
    project_tasks,
    projects,
    python_workspace,
    search,
    source_summaries,
    team_workspaces,
    usage,
)
from app.security_headers import security_headers_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    research_engine = make_engine(settings.database_url)
    literature_engine = make_engine(settings.effective_literature_database_url)
    app.state.research_engine = research_engine
    app.state.literature_engine = literature_engine
    app.state.research_session_factory = sessionmaker(
        bind=research_engine, autoflush=False, expire_on_commit=False
    )
    app.state.literature_session_factory = sessionmaker(
        bind=literature_engine, autoflush=False, expire_on_commit=False
    )
    initialize_database(research_engine, ResearchBase.metadata)
    ensure_user_username_column(research_engine)
    ensure_user_profile_picture_column(research_engine)
    ensure_project_paper_screening_columns(research_engine)
    ensure_notification_details_column(research_engine)
    ensure_document_chunk_page_column(research_engine)
    ensure_library_metadata_columns(research_engine)
    ensure_project_team_workspace_column(research_engine)
    ensure_project_collaboration_columns(research_engine)
    ensure_annotation_synthesis_columns(research_engine)
    ensure_python_workspace_files_column(research_engine)
    ensure_python_artifact_provenance_columns(research_engine)
    ensure_python_artifact_run_columns(research_engine)
    ensure_search_query_reproducibility_columns(research_engine)
    initialize_database(literature_engine, LiteratureBase.metadata)
    yield
    research_engine.dispose()
    literature_engine.dispose()


app = FastAPI(
    title="AI Research Assistant API",
    version="1.0.0",
    description="Manage research projects, documents, scholarly papers, and reviewed AI answers.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(security_headers_middleware)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(projects.router)
app.include_router(project_tasks.router)
app.include_router(project_home.router)
app.include_router(collaboration.router)
app.include_router(notifications.router)
app.include_router(team_workspaces.router)
app.include_router(collections.router)
app.include_router(latex.router)
app.include_router(python_workspace.router)
app.include_router(documents.router)
app.include_router(papers.router)
app.include_router(search.router)
app.include_router(annotations.router)
app.include_router(project_exports.router)
app.include_router(source_summaries.router)
app.include_router(assistant.router)
app.include_router(usage.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc: Exception):
    import logging

    logging.getLogger("app").exception("Unhandled request error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})
