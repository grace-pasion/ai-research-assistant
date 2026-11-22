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


def ensure_user_username_column(engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    with engine.begin() as connection:
        if "username" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32)"))
        connection.execute(
            text(
                "UPDATE users SET username = 'researcher_' || "
                "substr(replace(cast(user_id AS VARCHAR), '-', ''), 1, 12) "
                "WHERE username IS NULL"
            )
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
        )


def ensure_user_profile_picture_column(engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "profile_picture" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN profile_picture TEXT"))


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


def ensure_document_chunk_page_column(engine) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("document_chunks")}
    if "page_number" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE document_chunks ADD COLUMN page_number INTEGER")
            )
