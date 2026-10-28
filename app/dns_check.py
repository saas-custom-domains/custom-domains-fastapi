"""Used when you run the proxy yourself (DOMAINS_PROVIDER=caddy). With
SaaS Custom Domains, the API checks DNS for you."""

import asyncio

import dns.asyncresolver
import dns.exception

from app.hosts import normalize_host
from app.settings import settings


async def _lookup(host: str, rdtype: str) -> list[str]:
    try:
        answer = await dns.asyncresolver.resolve(
            host, rdtype, lifetime=5
        )
    except dns.exception.DNSException:
        return []
    return [normalize_host(r.to_text()) for r in answer]


async def points_at_us(host: str) -> bool:
    # *.localhost always resolves to this machine.
    if host.endswith(".localhost"):
        return True

    cnames, ips = await asyncio.gather(
        _lookup(host, "CNAME"), _lookup(host, "A")
    )
    server_ips = {
        ip.strip()
        for ip in settings.server_ips.split(",")
        if ip.strip()
    }
    return normalize_host(settings.cname_target) in cnames or bool(
        server_ips.intersection(ips)
    )
