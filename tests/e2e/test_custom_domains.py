import time

from playwright.sync_api import Page, expect


def unique(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


def add_domain(page: Page, tenant: str, host: str):
    section = page.get_by_test_id(f"tenant-{tenant}")
    section.get_by_label("Domain").fill(host)
    section.get_by_role("button", name="Add domain").click()


def test_connect_a_domain_serve_it_through_the_proxy_and_remove_it(
    page: Page, customer
):
    host = f"{unique('acme')}.test"
    page.goto("/")
    add_domain(page, "acme", host)
    row = page.get_by_test_id(f"domain-{host}")
    expect(row).to_be_visible()

    # The mock marks *.test as pointed after ~2s and sends webhooks.
    deadline = time.monotonic() + 15
    while (
        "Live" not in row.inner_text() and time.monotonic() < deadline
    ):
        time.sleep(0.5)
        page.reload()
    expect(row).to_contain_text("Live")

    # The help center, through the proxy.
    page.goto(f"http://{host}/")
    expect(page).to_have_title("Acme Robotics Help Center")
    page.get_by_role("link", name="Reset your robot").click()
    expect(
        page.get_by_role("heading", name="Reset your robot")
    ).to_be_visible()
    # Absolute URLs use the customer's domain, not the proxy's Host.
    expect(page.locator("link[rel=canonical]")).to_have_attribute(
        "href", f"https://{host}/articles/reset-your-robot"
    )

    # The feedback form posts and redirects on the customer's domain.
    article_api = f"http://{host}/api/articles/reset-your-robot"
    votes = customer.get(article_api).json()["helpful"]
    page.get_by_role("button", name="Yes").click()
    expect(page.get_by_role("status")).to_have_text(
        "Thanks for the feedback."
    )
    expect(page).to_have_url(
        f"http://{host}/articles/reset-your-robot?thanks=true"
    )

    api = customer.get(article_api).json()
    assert api["url"] == f"https://{host}/articles/reset-your-robot"
    assert api["helpful"] == votes + 1

    page.goto("/")
    row.get_by_role("button", name="Remove").click()
    expect(row).to_be_hidden()
    assert page.goto(f"http://{host}/").status == 404


def test_a_domain_that_does_not_point_at_us_stays_pending(page: Page):
    host = f"{unique('help')}.example.com"
    page.goto("/")
    add_domain(page, "globex", host)
    row = page.get_by_test_id(f"domain-{host}")
    row.get_by_role("button", name="Check DNS").click()
    expect(row).to_contain_text("Waiting for DNS")

    row.get_by_role("button", name="Remove").click()
    expect(row).to_be_hidden()


def test_rejects_our_own_domains(page: Page):
    page.goto("/")
    add_domain(page, "acme", "admin.helpdock.app")
    expect(
        page.get_by_test_id("tenant-acme").get_by_role("alert")
    ).to_have_text("That's one of our domains.")


def test_requests_that_skip_the_proxy_cannot_claim_a_domain(app):
    assert (
        app.get("/", headers={"X-Served-For": "acme.test"}).status_code
        == 403
    )
    wrong = app.get(
        "/",
        headers={
            "X-Served-For": "acme.test",
            "X-SaaS-Domains-Auth-Token": "guess",
        },
    )
    assert wrong.status_code == 403


def test_webhooks_need_the_right_token(app):
    res = app.post(
        "/webhooks/saascustomdomains?token=x",
        json={
            "event": "domain_dns_proxy_record_valid",
            "domain": {"uuid": "x"},
        },
    )
    assert res.status_code == 401


def test_unknown_domains_get_a_404(page: Page, app):
    # Stopped at the proxy...
    assert page.goto("http://unknown.test/").status == 404
    # ...and at the app, if a request reaches it some other way.
    res = app.get("/", headers={"Host": "unknown.test"})
    assert res.status_code == 404
    assert res.json() == {"detail": "Unknown domain"}
