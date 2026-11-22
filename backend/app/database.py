from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str):
    if url.startswith("postgres://"):
        url = f"postgresql+psycopg://{url[len('postgres://') :]}"
    elif url.startswith("postgresql://"):
        url = f"postgresql+psycopg://{url[len('postgresql://') :]}"
    return create_engine(url, pool_pre_ping=True)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker[Session] = request.app.state.research_session_factory
    with factory() as session:
        yield session


def get_literature_db(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker[Session] = request.app.state.literature_session_factory
    with factory() as session:
        yield session


def initialize_database(engine, metadata) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    metadata.create_all(engine)


def ensure_project_paper_screening_columns(engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("project_papers")}
    with engine.begin() as connection:
        if "screening_status" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE project_papers ADD COLUMN screening_status "
                    "VARCHAR(16) NOT NULL DEFAULT 'unread'"
                )
            )
        if "screening_note" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE project_papers ADD COLUMN screening_note "
                    "TEXT NOT NULL DEFAULT ''"
                )
            )
