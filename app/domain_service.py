"""Add, check and remove custom domains with either provider."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app import saas_domains
from app.dns_check import points_at_us
from app.models import CustomDomain, DomainStatus
from app.settings import settings


class DomainTakenError(Exception):
    pass


def _managed() -> bool:
    return settings.domains_provider == "saascustomdomains"


async def add_domain(
    session: Session, tenant_id: int, host: str, dns_contact: str | None = None
) -> CustomDomain:
    domain = CustomDomain(tenant_id=tenant_id, host=host)
    session.add(domain)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainTakenError(host) from None
    if not _managed():
        return domain

    try:
        res = await saas_domains.create_domain(host, dns_contact)
    except Exception:
        # Don't keep a row the proxy doesn't know about.
        session.delete(domain)
        session.commit()
        raise
    domain.provider_uuid = res["uuid"]
    session.commit()
    return domain


async def check_domain(session: Session, domain: CustomDomain) -> bool:
    if _managed() and domain.provider_uuid:
        res = await saas_domains.verify_dns(domain.provider_uuid)
        valid = res["dns_status"] == "valid"
    else:
        valid = await points_at_us(domain.host)
        # Caddy issues the certificate on the first HTTPS request.
        domain.https_ready = valid
    domain.status = DomainStatus.active if valid else DomainStatus.pending
    session.commit()
    return valid


async def remove_domain(session: Session, domain: CustomDomain) -> None:
    # Proxy first, database second: if the API call fails, the row is
    # still here and the user can retry.
    if _managed() and domain.provider_uuid:
        await saas_domains.delete_domain(domain.provider_uuid)
    session.delete(domain)
    session.commit()
