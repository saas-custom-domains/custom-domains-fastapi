import json

import httpx2
import pytest
from sqlmodel import select

from app import saas_domains
from app.models import CustomDomain, DomainStatus
from app.settings import settings

from .conftest import ACME


@pytest.fixture
def api(monkeypatch):
    """Answers SaaS Custom Domains API calls; tests set `api.responses`."""

    class Api:
        requests: list[httpx2.Request] = []
        responses: dict[tuple[str, str], httpx2.Response] = {}

        def handler(self, request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            key = (
                request.method,
                request.url.path.rsplit("/custom_domains", 1)[1],
            )
            return self.responses.get(key, httpx2.Response(500))

    fake = Api()
    fake.requests, fake.responses = [], {}
    real_client = saas_domains.client

    def client():
        c = real_client()
        c._transport = httpx2.MockTransport(fake.handler)
        return c

    monkeypatch.setattr(saas_domains, "client", client)
    return fake


def add(client, host, dns_contact=""):
    return client.post(
        "/domains",
        data={
            "tenant_id": str(ACME),
            "host": host,
            "dns_contact": dns_contact,
        },
    )


def test_add_domain_registers_it_with_the_api(client, session, api):
    api.responses[("POST", "")] = httpx2.Response(
        201, json={"uuid": "dom_1"}
    )

    res = add(client, " Help.Acme.com. ", "it@acme.com")

    assert res.status_code == 200  # after the redirect
    domain = session.exec(select(CustomDomain)).one()
    assert (domain.host, domain.provider_uuid) == (
        "help.acme.com",
        "dom_1",
    )
    assert domain.status == DomainStatus.pending
    request = api.requests[0]
    assert request.headers["authorization"] == "Bearer api_token"
    assert (
        request.url.path
        == "/api/v1/accounts/acc/upstreams/up/custom_domains"
    )
    assert json.loads(request.content) == {
        "host": "help.acme.com",
        "instructions_recipient": "it@acme.com",
    }
    assert "Waiting for DNS" in res.text


def test_a_failed_api_call_keeps_no_row(client, session, api):
    api.responses[("POST", "")] = httpx2.Response(
        400,
        json={
            "error": "Host has already been taken",
            "error_code": "host_taken",
        },
    )
    res = add(client, "help.acme.com")
    assert res.status_code == 400
    assert "Could not add the domain. Try again." in res.text
    assert session.exec(select(CustomDomain)).all() == []


def test_a_domain_can_only_be_connected_once(client, domains, api):
    res = add(client, "help.acme.test")
    assert (
        "help.acme.test is already connected to a help center."
        in res.text
    )
    assert api.requests == []


@pytest.mark.parametrize(
    ("host", "error"),
    [
        ("admin.helpdock.app", "That&#39;s one of our domains."),
        ("localhost", "isn&#39;t a valid domain."),
        ("not a domain", "isn&#39;t a valid domain."),
    ],
)
def test_rejects_our_domains_and_invalid_input(
    client, session, api, host, error
):
    res = add(client, host)
    assert res.status_code == 400
    assert error in res.text
    assert api.requests == []


def test_check_dns_marks_the_domain_active(client, session, api):
    session.add(
        CustomDomain(
            tenant_id=ACME, host="help.acme.com", provider_uuid="d1"
        )
    )
    session.commit()
    api.responses[("POST", "/d1/verify_dns_records")] = httpx2.Response(
        200, json={"dns_status": "valid"}
    )
    domain = session.exec(select(CustomDomain)).one()

    client.post(f"/domains/{domain.id}/check")

    session.refresh(domain)
    assert domain.status == DomainStatus.active


def test_remove_treats_404_as_already_gone(client, session, api):
    session.add(
        CustomDomain(
            tenant_id=ACME, host="help.acme.com", provider_uuid="d1"
        )
    )
    session.commit()
    api.responses[("DELETE", "/d1")] = httpx2.Response(
        404,
        json={
            "error": "Custom domain d1 not found.",
            "error_code": "not_found",
        },
    )
    domain = session.exec(select(CustomDomain)).one()

    client.post(f"/domains/{domain.id}/delete")

    assert session.exec(select(CustomDomain)).all() == []


def test_remove_keeps_the_row_if_the_api_fails(client, session, api):
    session.add(
        CustomDomain(
            tenant_id=ACME, host="help.acme.com", provider_uuid="d1"
        )
    )
    session.commit()
    api.responses[("DELETE", "/d1")] = httpx2.Response(503)
    domain = session.exec(select(CustomDomain)).one()

    with pytest.raises(saas_domains.SaasDomainsError):
        client.post(f"/domains/{domain.id}/delete")

    assert (
        session.exec(select(CustomDomain)).one().host == "help.acme.com"
    )


def test_caddy_mode_needs_no_api(client, session, api, monkeypatch):
    monkeypatch.setattr(settings, "domains_provider", "caddy")
    add(client, "help.acme.localhost")
    domain = session.exec(select(CustomDomain)).one()
    assert domain.provider_uuid is None

    client.post(f"/domains/{domain.id}/check")
    session.refresh(domain)
    assert domain.status == DomainStatus.active
    assert "Live" in client.get("/").text
    assert api.requests == []


def hook(client, event, uuid="d1", token="hook_token"):
    return client.post(
        f"/webhooks/saascustomdomains?token={token}",
        json={
            "event": event,
            "domain": {"uuid": uuid, "host": "help.acme.com"},
        },
    )


def test_webhooks_update_the_status(client, session):
    session.add(
        CustomDomain(
            tenant_id=ACME, host="help.acme.com", provider_uuid="d1"
        )
    )
    session.commit()

    assert (
        hook(client, "domain_dns_proxy_record_valid").status_code == 204
    )
    assert "DNS OK, waiting for HTTPS" in client.get("/").text
    hook(client, "tls_certificate_issued")
    assert "Live" in client.get("/").text
    hook(client, "domain_dns_proxy_record_invalid")
    assert "Waiting for DNS" in client.get("/").text


def test_webhooks_for_unknown_domains_are_acknowledged(client, session):
    assert (
        hook(
            client, "domain_dns_proxy_record_valid", uuid="other"
        ).status_code
        == 204
    )
    assert (
        hook(client, "domain_deleted", uuid="other").status_code == 204
    )


def test_webhooks_need_the_right_token(client, session, monkeypatch):
    assert (
        hook(
            client, "domain_dns_proxy_record_valid", token="x"
        ).status_code
        == 401
    )
    # Checked before the body, so junk with a bad token is still a 401.
    junk = client.post(
        "/webhooks/saascustomdomains?token=x", content=b"{"
    )
    assert junk.status_code == 401

    monkeypatch.setattr(settings, "scd_webhook_token", "")
    assert (
        hook(
            client, "domain_dns_proxy_record_valid", token=""
        ).status_code
        == 401
    )


def test_webhooks_arrive_on_internal_hostnames(client, session):
    res = client.post(
        "/webhooks/saascustomdomains?token=hook_token",
        headers={"host": "app:3000"},
        json={"event": "domain_created", "domain": {"uuid": "d9"}},
    )
    assert res.status_code == 204


def test_caddy_ask(client, domains):
    assert (
        client.get("/caddy/ask?domain=help.acme.test").status_code
        == 200
    )
    assert (
        client.get("/caddy/ask?domain=help.globex.test").status_code
        == 404
    )
    assert (
        client.get("/caddy/ask?domain=evil.example").status_code == 404
    )
