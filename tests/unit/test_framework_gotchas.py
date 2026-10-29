"""What plain FastAPI does behind a proxy. If one of these starts failing
after an upgrade, the behaviour changed and the README needs updating."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .conftest import proxied


def test_trusted_host_middleware_rejects_customer_domains():
    plain = FastAPI()
    plain.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["app.helpdock.app"]
    )
    plain.get("/")(lambda: "ok")
    client = TestClient(plain)

    # Behind SaaS Custom Domains, Host is your own hostname: allowed.
    assert (
        client.get("/", headers=proxied("help.acme.test")).status_code
        == 200
    )
    # Local development on the domain, a health check by IP, a webhook
    # on an internal name:
    for host in ["help.acme.test", "10.0.3.17:3000", "app:3000"]:
        res = client.get("/", headers={"host": host})
        assert (res.status_code, res.text) == (
            400,
            "Invalid host header",
        )


def test_our_app_accepts_what_trusted_host_middleware_rejects(
    client, domains
):
    assert (
        client.get("/", headers={"host": "help.acme.test"}).status_code
        == 200
    )
    assert (
        client.get(
            "/up", headers={"host": "10.0.3.17:3000"}
        ).status_code
        == 200
    )
    assert (
        client.get("/", headers={"host": "app:3000"}).status_code == 200
    )


def test_url_for_uses_the_proxys_host():
    plain = FastAPI()

    @plain.get("/articles/{slug}", name="article")
    def article(slug: str):
        return slug

    @plain.post("/articles/{slug}/feedback")
    def feedback(request: Request, slug: str):
        return RedirectResponse(
            request.url_for("article", slug=slug), status_code=303
        )

    res = TestClient(plain).post(
        "/articles/reset/feedback",
        headers=proxied("help.acme.test", host="app:3000"),
        follow_redirects=False,
    )
    # The visitor is sent to your app's own host, over plain HTTP.
    assert res.headers["location"] == "http://app:3000/articles/reset"


def test_uvicorn_proxy_headers_never_touch_the_host():
    plain = FastAPI()

    @plain.get("/", name="home")
    def home(request: Request):
        return {
            "url": str(request.url_for("home")),
            "client": request.client.host,
        }

    # Like --forwarded-allow-ips="*", and even with X-Forwarded-Host set to
    # the customer's domain (an option support can turn on).
    trusting = ProxyHeadersMiddleware(plain, trusted_hosts="*")
    res = TestClient(trusting).get(
        "/",
        headers=proxied(
            "help.acme.test",
            host="app:3000",
            **{"x-forwarded-host": "help.acme.test"},
        ),
    )
    assert res.json() == {
        "url": "https://app:3000/",
        "client": "203.0.113.7",
    }


def test_http_exception_in_http_middleware_is_a_500():
    plain = FastAPI()

    @plain.middleware("http")
    async def check_token(request: Request, call_next):
        if request.headers.get("x-served-for"):
            raise HTTPException(status_code=403)
        return await call_next(request)

    plain.get("/")(lambda: "ok")
    res = TestClient(plain, raise_server_exceptions=False).get(
        "/", headers={"x-served-for": "help.acme.test"}
    )
    assert (res.status_code, res.text) == (500, "Internal Server Error")
