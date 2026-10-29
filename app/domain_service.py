"""Add, check and remove custom domains at SaaS Custom Domains."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app import saas_domains
from app.models import CustomDomain, DomainStatus


class DomainTakenError(Exception):
    pass


async def add_domain(
    session: Session,
    tenant_id: int,
    host: str,
    dns_contact: str | None = None,
) -> CustomDomain:
    domain = CustomDomain(tenant_id=tenant_id, host=host)
    session.add(domain)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DomainTakenError(host) from None

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
    if not domain.provider_uuid:
        return False
    res = await saas_domains.verify_dns(domain.provider_uuid)
    valid = res["dns_status"] == "valid"
    domain.status = (
        DomainStatus.active if valid else DomainStatus.pending
    )
    session.commit()
    return valid


async def remove_domain(session: Session, domain: CustomDomain) -> None:
    # Proxy first, database second: if the API call fails, the row is
    # still here and the user can retry.
    if domain.provider_uuid:
        await saas_domains.delete_domain(domain.provider_uuid)
    session.delete(domain)
    session.commit()
