import dns.resolver
import pytest

from app import dns_check
from app.settings import settings

pytestmark = pytest.mark.anyio


class Record:
    def __init__(self, text):
        self.text = text

    def to_text(self):
        return self.text


@pytest.fixture
def records(monkeypatch):
    table: dict[tuple[str, str], list[str]] = {}

    async def resolve(host, rdtype, lifetime=None):
        if (host, rdtype) not in table:
            raise dns.resolver.NXDOMAIN
        return [Record(r) for r in table[(host, rdtype)]]

    monkeypatch.setattr(dns_check.dns.asyncresolver, "resolve", resolve)
    monkeypatch.setattr(settings, "cname_target", "in.helpdock.app")
    monkeypatch.setattr(settings, "server_ips", "198.51.100.10")
    return table


async def test_localhost_always_points_at_us(records):
    assert await dns_check.points_at_us("help.acme.localhost")


async def test_cname_to_our_target(records):
    records[("help.acme.com", "CNAME")] = ["In.Helpdock.app."]
    assert await dns_check.points_at_us("help.acme.com")


async def test_a_record_to_our_server(records):
    records[("acme.com", "A")] = ["198.51.100.10"]
    assert await dns_check.points_at_us("acme.com")


async def test_anything_else_does_not(records):
    records[("help.acme.com", "CNAME")] = ["somewhere.else."]
    assert not await dns_check.points_at_us("help.acme.com")
    assert not await dns_check.points_at_us("missing.example")
