from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Article, Tenant
from app.settings import settings

engine = create_engine(
    settings.database_url,
    # SQLite: FastAPI may use the session from another thread.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(connection, _record):
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def init_db() -> None:
    if engine.url.database:
        Path(engine.url.database).parent.mkdir(
            parents=True, exist_ok=True
        )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(Tenant)).first() is None:
            _seed(session)


def _seed(session: Session) -> None:
    acme = Tenant(slug="acme", name="Acme Robotics")
    globex = Tenant(slug="globex", name="Globex Payroll")
    session.add_all([acme, globex])
    session.flush()
    session.add_all(
        [
            Article(
                tenant_id=acme.id,
                slug="reset-your-robot",
                title="Reset your robot",
                body="Hold the power button for ten seconds until the "
                "light turns blue, then pair it again from the app.",
            ),
            Article(
                tenant_id=acme.id,
                slug="replace-the-battery",
                title="Replace the battery",
                body="Turn the robot over, undo the two screws on the "
                "battery cover and slide the old battery out.",
            ),
            Article(
                tenant_id=globex.id,
                slug="run-payroll",
                title="Run your first payroll",
                body="Add your employees, check their tax details and "
                "press Run payroll before the cut-off on the 25th.",
            ),
        ]
    )
    session.commit()
