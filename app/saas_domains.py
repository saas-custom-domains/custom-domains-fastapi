"""A small client for the SaaS Custom Domains API.

Docs: https://docs.saascustomdomains.com/custom-domains
"""

from typing import Any

import httpx2

from app.settings import settings


class SaasDomainsError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"SaaS Custom Domains API {status_code}: {body}")
        self.status_code = status_code


def client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {settings.scd_api_token}"},
        timeout=10,
    )


async def _request(method: str, path: str = "", json: Any = None) -> dict:
    url = (
        f"{settings.scd_api_url}/api/v1/accounts/{settings.scd_account_uuid}"
        f"/upstreams/{settings.scd_upstream_uuid}/custom_domains{path}"
    )
    async with client() as http:
        res = await http.request(method, url, json=json)
    if res.is_error:
        raise SaasDomainsError(res.status_code, res.text)
    return res.json()


async def create_domain(host: str, instructions_recipient: str | None = None) -> dict:
    body = {"host": host}
    if instructions_recipient:
        # We email this address the exact DNS records to add.
        body["instructions_recipient"] = instructions_recipient
    return await _request("POST", json=body)


async def verify_dns(uuid: str) -> dict:
    return await _request("POST", f"/{uuid}/verify_dns_records")


async def delete_domain(uuid: str) -> None:
    try:
        await _request("DELETE", f"/{uuid}")
    except SaasDomainsError as e:
        # Already gone is fine: the goal is that it doesn't exist.
        if e.status_code != 404:
            raise
