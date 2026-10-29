"""The owner dashboard and the webhook endpoint. Both live on your own
hostnames (APP_HOSTS)."""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app import domain_service
from app.db import SessionDep
from app.hosts import (
    is_reserved_host,
    is_valid_host,
    normalize_host,
    secure_compare,
)
from app.models import CustomDomain, DomainStatus, Tenant
from app.settings import settings
from app.templating import templates

log = logging.getLogger(__name__)
router = APIRouter()

# This example has no login. In your app, check that the signed-in user
# owns the tenant (and the domain) in every one of these routes.


def render_dashboard(
    request: Request,
    session: Session,
    errors: dict[int, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    tenants = session.exec(select(Tenant).order_by(Tenant.id)).all()
    domains = session.exec(
        select(CustomDomain).order_by(CustomDomain.id)
    ).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "tenants": tenants,
            "domains": domains,
            "errors": errors or {},
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(request: Request, session: SessionDep):
    return render_dashboard(request, session)


@router.post("/domains", response_class=HTMLResponse)
async def add_domain(
    request: Request,
    session: SessionDep,
    tenant_id: Annotated[int, Form()],
    host: Annotated[str, Form()],
    dns_contact: Annotated[str, Form()] = "",
):
    host = normalize_host(host)
    error = None
    if not is_valid_host(host):
        error = f'"{host}" isn\'t a valid domain.'
    elif is_reserved_host(host):
        error = "That's one of our domains."
    else:
        try:
            await domain_service.add_domain(
                session, tenant_id, host, dns_contact.strip() or None
            )
        except domain_service.DomainTakenError:
            error = f"{host} is already connected to a help center."
        except Exception:
            log.exception("Could not add %s", host)
            error = "Could not add the domain. Try again."
    if error:
        return render_dashboard(
            request, session, {tenant_id: error}, 400
        )
    return RedirectResponse(
        router.url_path_for("dashboard"), status_code=303
    )


def get_domain(domain_id: int, session: SessionDep) -> CustomDomain:
    domain = session.get(CustomDomain, domain_id)
    if domain is None:
        raise HTTPException(status_code=404)
    return domain


DomainDep = Annotated[CustomDomain, Depends(get_domain)]


@router.post("/domains/{domain_id}/check")
async def check_domain(domain: DomainDep, session: SessionDep):
    await domain_service.check_domain(session, domain)
    return RedirectResponse(
        router.url_path_for("dashboard"), status_code=303
    )


@router.post("/domains/{domain_id}/delete")
async def remove_domain(domain: DomainDep, session: SessionDep):
    await domain_service.remove_domain(session, domain)
    return RedirectResponse(
        router.url_path_for("dashboard"), status_code=303
    )


def verify_webhook_token(token: str = "") -> None:
    # Runs before the body is parsed, so a bad token is a 401 even when
    # the body is junk.
    expected = settings.scd_webhook_token
    if not expected or not secure_compare(token, expected):
        raise HTTPException(status_code=401)


class WebhookDomain(BaseModel):
    uuid: str


class WebhookEvent(BaseModel):
    event: str
    domain: WebhookDomain | None = None


@router.post(
    "/webhooks/saascustomdomains",
    status_code=204,
    dependencies=[Depends(verify_webhook_token)],
)
def webhook(payload: WebhookEvent, session: SessionDep):
    """Events: https://docs.saascustomdomains.com/webhooks"""
    domain = (
        payload.domain
        and session.exec(
            select(CustomDomain).where(
                CustomDomain.provider_uuid == payload.domain.uuid
            )
        ).first()
    )
    # Not ours (or already removed): acknowledge so it isn't retried.
    if not domain:
        return Response(status_code=204)

    match payload.event:
        case "domain_dns_proxy_record_valid":
            domain.status = DomainStatus.active
        case "domain_dns_proxy_record_invalid":
            domain.status = DomainStatus.pending
        case "tls_certificate_issued":
            domain.https_ready = True
    session.commit()
    return Response(status_code=204)
