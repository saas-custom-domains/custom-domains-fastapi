from sqlmodel import select

from app.models import Feedback
from app.settings import settings

from .conftest import proxied


def test_app_host_serves_the_dashboard(client, domains):
    res = client.get("/")
    assert res.status_code == 200
    assert "Helpdock dashboard" in res.text


def test_help_center_is_hidden_on_the_app_host(client, domains):
    assert client.get("/articles/reset-your-robot").status_code == 404
    assert client.get("/api/articles").status_code == 404


def test_active_domain_serves_its_help_center(client, domains):
    # Your own proxy (Caddy) keeps the customer's domain in Host.
    res = client.get("/", headers={"host": "Help.Acme.test:8443"})
    assert res.status_code == 200
    assert "Acme Robotics Help Center" in res.text


def test_pending_and_unknown_domains_get_404(client, domains):
    assert client.get("/", headers={"host": "help.globex.test"}).status_code == 404
    assert client.get("/", headers={"host": "evil.example"}).status_code == 404
    assert client.get("/", headers=proxied("evil.example")).status_code == 404


def test_dashboard_is_not_reachable_on_a_customer_domain(client, domains):
    res = client.post(
        "/domains",
        headers={"host": "help.acme.test"},
        data={"tenant_id": "1", "host": "x.example.com"},
    )
    assert res.status_code in (404, 405)


def test_reads_x_served_for_with_the_proxy_token(client, domains):
    res = client.get("/", headers=proxied("help.acme.test"))
    assert res.status_code == 200
    assert "Acme Robotics Help Center" in res.text


def test_rejects_x_served_for_without_the_right_token(client, domains):
    spoofed = {"host": "app.helpdock.app", "x-served-for": "help.acme.test"}
    assert client.get("/", headers=spoofed).status_code == 403
    assert client.get("/", headers=proxied("help.acme.test", "nope")).status_code == 403
    assert client.get("/", headers=proxied("help.acme.test", "")).status_code == 403


def test_rejects_everything_when_the_token_is_not_set(client, domains, monkeypatch):
    monkeypatch.setattr(settings, "proxy_auth_token", "")
    assert client.get("/", headers=proxied("help.acme.test", "")).status_code == 403


def test_health_check_works_on_any_host(client):
    assert client.get("/up", headers={"host": "10.0.3.17:3000"}).status_code == 200


def test_absolute_urls_use_the_customer_domain(client, domains):
    # Fails without as_seen_by_visitor(): url_for() would build
    # "http://app.helpdock.app/articles/..." from the proxy's Host.
    res = client.get("/api/articles", headers=proxied("help.acme.test"))
    assert res.json()[0]["url"] == "https://help.acme.test/articles/reset-your-robot"

    page = client.get("/articles/reset-your-robot", headers=proxied("help.acme.test"))
    assert (
        '<link rel="canonical" href="https://help.acme.test/articles/reset-your-robot">'
        in page.text
    )


def test_feedback_form_through_the_proxy(client, session, domains):
    res = client.post(
        "/articles/reset-your-robot/feedback",
        headers=proxied("help.acme.test"),
        data={"helpful": "yes"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    # Relative, so the browser stays on the customer's domain.
    assert res.headers["location"] == "/articles/reset-your-robot?thanks=true"

    feedback = session.exec(select(Feedback)).one()
    assert feedback.helpful
    # request.client is the visitor (X-SaaS-Domains-IP), not the proxy.
    assert feedback.client_ip == "203.0.113.7"

    detail = client.get(
        "/api/articles/reset-your-robot", headers=proxied("help.acme.test")
    )
    assert detail.json()["helpful"] == 1


def test_feedback_only_reaches_the_domains_own_articles(client, domains):
    # run-payroll belongs to Globex, so it doesn't exist on Acme's domain.
    res = client.post(
        "/articles/run-payroll/feedback",
        headers=proxied("help.acme.test"),
        data={"helpful": "yes"},
    )
    assert res.status_code == 404
