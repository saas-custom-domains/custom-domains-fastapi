import os
import tempfile

# Settings are read on import, so configure them before importing the app.
os.environ.update(
    DATABASE_URL=f"sqlite:///{tempfile.mkdtemp()}/test.db",
    APP_HOSTS="localhost,app.helpdock.app,app",
    APP_DOMAIN="helpdock.app",
    DOMAINS_PROVIDER="saascustomdomains",
    SCD_API_URL="http://scd.test",
    SCD_API_TOKEN="api_token",
    SCD_ACCOUNT_UUID="acc",
    SCD_UPSTREAM_UUID="up",
    PROXY_AUTH_TOKEN="test_token",
    SCD_WEBHOOK_TOKEN="hook_token",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, delete  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CustomDomain, DomainStatus, Feedback  # noqa: E402

ACME, GLOBEX = 1, 2


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def client():
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def session(client):
    with Session(engine) as s:
        s.exec(delete(Feedback))
        s.exec(delete(CustomDomain))
        s.commit()
        yield s


@pytest.fixture
def domains(session):
    session.add_all(
        [
            CustomDomain(
                tenant_id=ACME,
                host="help.acme.test",
                status=DomainStatus.active,
            ),
            CustomDomain(tenant_id=GLOBEX, host="help.globex.test"),
        ]
    )
    session.commit()


# What SaaS Custom Domains sends: Host is your own hostname, the
# customer's domain is in X-Served-For.
def proxied(
    domain: str, token: str = "test_token", **extra: str
) -> dict[str, str]:
    return {
        "host": "app.helpdock.app",
        "x-served-for": domain,
        "x-saas-domains-auth-token": token,
        "x-saas-domains-ip": "203.0.113.7",
        "x-forwarded-for": "203.0.113.7",
        "x-forwarded-proto": "https",
        "x-forwarded-host": "app.helpdock.app",
        **extra,
    }
