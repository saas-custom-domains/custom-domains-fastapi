from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db import SessionDep
from app.hosts import is_app_host, normalize_host, secure_compare
from app.models import CustomDomain, DomainStatus, Tenant
from app.settings import settings

# Load balancers and Docker call this by IP address, so it skips the
# host check.
UNCHECKED_PATHS = {"/up"}


class CustomerDomainMiddleware:
    """Sends requests for your own hostnames to the dashboard app and
    requests for customer domains to the help center app.

    Behind SaaS Custom Domains, Host is your own hostname and the
    customer's domain arrives in X-Served-For. It's only trusted with
    the upstream's auth token, or anyone could claim any customer's
    domain by sending the header themselves.
    """

    def __init__(self, app: ASGIApp, site: ASGIApp) -> None:
        self.app = app
        self.site = site

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNCHECKED_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        served_for = headers.get("x-served-for")
        if served_for is not None and not has_valid_proxy_token(headers):
            await PlainTextResponse("Forbidden", 403)(scope, receive, send)
            return

        host = normalize_host(served_for or headers.get("host", ""))
        if is_app_host(host):
            await self.app(scope, receive, send)
            return

        scope = dict(scope, state={**scope.get("state", {}), "customer_host": host})
        if served_for is not None:
            scope = as_seen_by_visitor(scope, host, headers)
        await self.site(scope, receive, send)


def has_valid_proxy_token(headers: Headers) -> bool:
    expected = settings.proxy_auth_token
    token = headers.get("x-saas-domains-auth-token", "")
    return bool(expected) and secure_compare(token, expected)


def as_seen_by_visitor(scope: Scope, host: str, headers: Headers) -> Scope:
    """Rewrite a proxied request so request.url, url_for() and
    request.client describe the visitor's request, not the proxy's.

    Starlette builds URLs from Host, which the proxy sets to your own
    hostname, and Uvicorn only reads X-Forwarded-Proto and
    X-Forwarded-For from IPs in --forwarded-allow-ips. The auth token
    already proved where this request came from, so use what the proxy
    says.
    """
    raw = [(k, v) for k, v in scope["headers"] if k != b"host"]
    raw.append((b"host", host.encode("latin-1")))
    scope = dict(scope, headers=raw)
    scope["scheme"] = headers.get("x-forwarded-proto", "https")
    if client_ip := headers.get("x-saas-domains-ip"):
        scope["client"] = (client_ip, 0)
    return scope


def find_tenant_by_active_host(session: Session, host: str) -> Tenant | None:
    """The one lookup every customer-facing request depends on. Keep the
    unique index on custom_domain.host."""
    return session.exec(
        select(Tenant)
        .join(CustomDomain)
        .where(CustomDomain.host == host, CustomDomain.status == DomainStatus.active)
    ).first()


def current_tenant(request: Request, session: SessionDep) -> Tenant:
    tenant = find_tenant_by_active_host(session, request.state.customer_host)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown domain")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(current_tenant)]
