from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, create_engine

from app.db import models  # noqa: F401  (registers tables)


def make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url)
    # Sync sessions run on worker threads (asyncio.to_thread), so the connection must be shareable.
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _add_owner_hash(engine)


def _add_owner_hash(engine: Engine) -> None:
    """A database made before `owner_hash` existed keeps its rows: add the column (and its index)
    in place. `create_all` never alters an existing table. Old rows stay NULL, so no list shows
    them."""
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("debate")}
        if "owner_hash" not in columns:
            conn.execute(text("ALTER TABLE debate ADD COLUMN owner_hash VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_debate_owner_hash ON debate (owner_hash)"))
