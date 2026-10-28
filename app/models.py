from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel, UniqueConstraint


def _now() -> datetime:
    return datetime.now(UTC)


class Tenant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True)
    name: str


class Article(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    slug: str
    title: str
    body: str


class Feedback(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True)
    helpful: bool
    client_ip: str | None = None
    created_at: datetime = Field(default_factory=_now)


class DomainStatus(StrEnum):
    pending = "pending"
    active = "active"


class CustomDomain(SQLModel, table=True):
    __tablename__ = "custom_domain"

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    # Normalized (lowercase, no port, no trailing dot). The unique index
    # is what every customer request is looked up by.
    host: str = Field(unique=True)
    status: DomainStatus = DomainStatus.pending
    https_ready: bool = False
    # The domain's UUID at SaaS Custom Domains.
    provider_uuid: str | None = Field(default=None, unique=True)
    created_at: datetime = Field(default_factory=_now)
