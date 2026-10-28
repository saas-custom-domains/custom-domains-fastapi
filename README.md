# Custom domains in FastAPI

An example FastAPI app where each customer connects their own domain. It's a small help center product, Helpdock: every company gets a help center with articles, a JSON API and a "Was this helpful?" form, and can serve it on `help.theircompany.com` instead of a Helpdock URL.

It goes with the guide [How to Add Custom Domains to a FastAPI App](https://saascustomdomains.com/blog/posts/custom-domains-fastapi).

What's in it:

- One ASGI middleware, `CustomerDomainMiddleware`, decides per request: your own hostnames get the dashboard app, active customer domains get the help center app, anything else gets a 404. It replaces Starlette's `TrustedHostMiddleware`.
- Requests from the [SaaS Custom Domains](https://saascustomdomains.com) proxy are accepted only with the upstream's auth token, so nobody can claim a customer's domain by sending `X-Served-For` themselves.
- `request.url_for()`, `request.client` and the feedback form work on custom domains behind the proxy (see [url_for() returns your app's hostname](#url_for-returns-your-apps-hostname)).
- The tenant is a FastAPI dependency (`CurrentTenant`), required by every route of the help center app.
- A dashboard to add a domain, check its DNS and remove it. Webhooks update the status.
- Two ways to run HTTPS: SaaS Custom Domains (default), or your own Caddy with on-demand TLS.

## Run it in 2 minutes

You need Docker.

```bash
git clone https://github.com/saas-custom-domains/custom-domains-fastapi
cd custom-domains-fastapi
docker compose up --build
```

1. Open http://localhost:3000 and add `acme.localhost` to Acme Robotics.
2. Within a few seconds the status changes to **Live**: the mock API "found" the DNS records and sent a webhook.
3. Open http://acme.localhost. The request goes through the mock proxy on port 80, exactly like a real customer domain goes through SaaS Custom Domains, and you see Acme's help center. Open an article and answer "Was this helpful?". http://acme.localhost/api/articles is the JSON API.

`*.localhost` always resolves to your own machine in Chrome, Firefox, Safari and curl, so there's nothing to add to `/etc/hosts`.

The mock is [scd-mock](https://github.com/saas-custom-domains/scd-mock): a local copy of the SaaS Custom Domains API and proxy, so you can try everything without an account.

### Without Docker

You need [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
uv run fastapi dev
```

Add a domain such as `acme.localhost`, click Check DNS, and open http://acme.localhost:8000. Without the mock, set `DOMAINS_PROVIDER=caddy` in `.env` so adding a domain doesn't call the API; `*.localhost` domains count as pointed at you.

## How it works

```
Browser ── help.acme.com ──▶ SaaS Custom Domains ──▶ your FastAPI app
                             (TLS certificate,       Host: app.helpdock.app
                              proxy)                 X-Served-For: help.acme.com
                                                     X-SaaS-Domains-Auth-Token: …
```

| File | What it does |
| --- | --- |
| `app/tenancy.py` | `CustomerDomainMiddleware` (token check, host, dispatch) and the `CurrentTenant` dependency |
| `app/site.py` | The customer's help center: HTML pages, feedback form, JSON API |
| `app/dashboard.py` | Dashboard, webhook endpoint, Caddy's ask endpoint |
| `app/domain_service.py` | Add, check and remove domains with either provider |
| `app/saas_domains.py` | API client for SaaS Custom Domains (httpx2) |
| `app/dns_check.py` | Async DNS check with dnspython, for running your own proxy |
| `app/models.py` | SQLModel tables; `custom_domain.host` has a unique index |

SaaS Custom Domains keeps `Host` and `X-Forwarded-Host` set to your app's own hostname, so your hosting platform routes the request to you, and sends the customer's domain in `X-Served-For`. The middleware only reads `X-Served-For` when `X-SaaS-Domains-Auth-Token` matches `PROXY_AUTH_TOKEN` (compared with `hmac.compare_digest`), and returns 403 otherwise, including when `PROXY_AUTH_TOKEN` isn't set.

## FastAPI gotchas

### "Invalid host header"

Starlette's `TrustedHostMiddleware` answers any request whose `Host` isn't in `allowed_hosts` with a plain-text 400:

```
Invalid host header
```

Behind SaaS Custom Domains that check passes, because `Host` is your own hostname. It fails everywhere else you'd expect a customer domain or an internal name:

- with your own proxy (Caddy), where `Host` is the customer's domain, so every customer gets the 400;
- for health checks from Docker or a load balancer, which use an IP address;
- for webhooks sent to an internal name, like the mock's `Host: app:3000`.

A fixed list can't hold your customers' domains, and the middleware doesn't look at `X-Served-For` at all, so it doesn't protect anything here either. This app drops it: `CustomerDomainMiddleware` lets your own hostnames (`APP_HOSTS`) through, looks every other host up in the `custom_domain` table, and returns 404 for unknown and pending domains. `/up` skips the check. `tests/unit/test_framework_gotchas.py` checks the 400 and its text, so a Starlette release that changes it shows up in CI.

### url_for() returns your app's hostname

SaaS Custom Domains sends your app's own hostname in `Host`, because that's what your hosting platform routes on, and the customer's domain separately in `X-Served-For`. Starlette builds absolute URLs from `Host`, so this:

```python
return RedirectResponse(
    request.url_for("article", slug=slug), status_code=303
)
```

sends a visitor on `https://help.acme.com` to `http://app.helpdock.app/articles/...` (in `docker compose`, `http://app:3000/...`), where the customer's article doesn't exist. The same goes for `url_for()` in Jinja templates, canonical links, and URLs in JSON responses.

Uvicorn's `--proxy-headers` (on by default) is about something else: it rewrites the scheme from `X-Forwarded-Proto` and `request.client` from `X-Forwarded-For`, and only for connections from `--forwarded-allow-ips` (default `127.0.0.1,::1`, or `FORWARDED_ALLOW_IPS`). It never changes `Host`, and nothing in Uvicorn or Starlette reads `X-Forwarded-Host`.

If your app needs the customer's domain for redirects, links or absolute URLs, hand it `X-Served-For` once the token has proved the request came through the proxy. That's what `as_seen_by_visitor()` in `app/tenancy.py` does: it rewrites the ASGI scope so `Host` is the `X-Served-For` domain, the scheme comes from `X-Forwarded-Proto`, and `request.client` comes from `X-SaaS-Domains-IP`. After that, `request.url`, `url_for()` and `request.client` describe the visitor's request. Redirects in this app are relative anyway (`site.url_path_for(...)`), so the browser stays on whatever domain it's on, including `http://acme.localhost` locally.

(Support can also put the customer's domain in `X-Forwarded-Host`, but FastAPI ignores that header.)

### --forwarded-allow-ips in Docker

The default `--forwarded-allow-ips` trusts only `127.0.0.1`. On Docker Desktop, requests published to your Mac's ports arrive from `127.0.0.1`, so `X-Forwarded-Proto` is trusted and URLs are `https://`. In `docker compose` or production, the proxy connects from another address (`172.x.x.x` here), Uvicorn ignores the headers, `request.url.scheme` is `http` and `request.client.host` is the proxy's IP. `--forwarded-allow-ips="*"` fixes that but lets anyone who can reach your app directly set `X-Forwarded-For`.

This app doesn't need either for customer domains, because it trusts the proxy by token rather than by IP. You still need `--forwarded-allow-ips` (or `FORWARDED_ALLOW_IPS`) with your load balancer's addresses for your own hostname, and with Caddy's address if you run the DIY setup in production.

### HTTPException in middleware is a 500

If you write the token check as an `@app.middleware("http")` function and `raise HTTPException(status_code=403)` in it, the client gets `500 Internal Server Error`: exception handlers don't cover middleware. Return a response instead (this app returns `PlainTextResponse("Forbidden", 403)`).

### The tenant as a dependency

`current_tenant()` looks up the active domain and raises 404 if there isn't one. The help center app requires it on every route:

```python
site = FastAPI(dependencies=[Depends(current_tenant)], docs_url=None, ...)
```

and routes that need the tenant take `tenant: CurrentTenant`. FastAPI caches a dependency per request, so the lookup runs once. It's a plain `def`, so the database call runs in the threadpool. The feedback form takes the tenant from the domain, never from the form, so a visitor on Acme's domain can't post feedback to another company's article.

## Run your own proxy instead (Caddy)

```bash
DOMAINS_PROVIDER=caddy docker compose --profile diy up --build
```

Add `acme.localhost` in the dashboard and click Check DNS, then:

```bash
curl -k https://acme.localhost/
```

Caddy asks `/caddy/ask` before issuing a certificate, and only active domains get one. Locally it uses Caddy's internal CA, hence `-k`. The DNS check uses `dns.asyncresolver` and counts a CNAME to `CNAME_TARGET` or an A record in `SERVER_IPS`. In production you'd remove `internal` from the `Caddyfile`, run it on a server with a static IP, start the app with `--forwarded-allow-ips` set to Caddy's address, and then own certificate storage, renewals, rate limits and monitoring yourself.

## Use it with your SaaS Custom Domains account

1. [Create an API token](https://app.saascustomdomains.com/api_tokens) and an upstream pointing at your deployed app.
2. Set the environment variables from `.env.example`: `SCD_API_TOKEN`, `SCD_ACCOUNT_UUID`, `SCD_UPSTREAM_UUID`, `PROXY_AUTH_TOKEN` (the upstream's auth token), `SCD_WEBHOOK_TOKEN` (from the webhook you create in the dashboard), and `APP_HOSTS`.
3. Remove `SCD_API_URL` so the client talks to the real API.

`APP_HOSTS` must list every hostname your own traffic arrives on: your app's domain, plus any internal name your platform uses to reach the app. The middleware treats any other host as a customer domain and returns 404 if it isn't connected. (In `compose.yaml` that's why `app` is listed: webhooks from the mock arrive as `Host: app:3000`.) The health check at `/up` skips the middleware, because load balancers call it by IP address.

Your customers point a CNAME at `in.saascustomdomains.com` (or A records at our two static IPs for a root domain). See the [docs](https://docs.saascustomdomains.com).

## Tests

```bash
uv run pytest                  # unit tests (middleware, tokens, API client, webhooks)
docker compose up -d --build --wait
uv run playwright install chromium
uv run pytest tests/e2e        # end to end, through the mock proxy
```

The end-to-end tests use `*.test` domains and send the browser's requests for them to the mock proxy, so nothing depends on DNS or on port 80. To run a second stack side by side, set `APP_PORT`, `SCD_MOCK_API_PORT` and `SCD_MOCK_PROXY_PORT` for both `docker compose` and `pytest tests/e2e`.

CI runs both on every push and once a week, so a new FastAPI, Starlette or Uvicorn release that breaks something shows up here first.

## Tested with

| | Version |
| --- | --- |
| FastAPI | 0.162.0 |
| Starlette | 1.10.0 |
| Uvicorn | 0.54.0 |
| SQLModel | 0.0.48 (SQLAlchemy 2.1.6) |
| httpx2 | 2.16.0 |
| dnspython | 2.9.0 |
| Python | 3.13 |

Last checked: 2026-10-28.

The API client uses [httpx2](https://github.com/pydantic/httpx2), the maintained continuation of httpx with the same API. Starlette 1.10's `TestClient` warns "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead."

## Not production-ready on purpose

There's no login and no CSRF protection on the dashboard. In your app, check in every dashboard route that the signed-in user owns the tenant and the domain. SQLite keeps the example small; with Postgres, the queries stay the same.

## License

MIT
