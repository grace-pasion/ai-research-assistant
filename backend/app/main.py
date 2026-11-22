from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.database import initialize_database, make_engine
from app.models import LiteratureBase, ResearchBase
from app.routers import assistant, auth, documents, papers, projects


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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(papers.router)
app.include_router(assistant.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc: Exception):
    import logging

    logging.getLogger("app").exception("Unhandled request error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})
