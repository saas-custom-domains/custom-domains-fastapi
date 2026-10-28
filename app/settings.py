from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Hostnames that serve the dashboard (comma-separated, no port).
    app_hosts: str = "localhost"
    # Customers can't claim this domain or its subdomains.
    app_domain: str = ""

    # "saascustomdomains", or "caddy" if you run your own proxy.
    domains_provider: Literal["saascustomdomains", "caddy"] = "saascustomdomains"

    scd_api_url: str = "https://app.saascustomdomains.com"
    scd_api_token: str = ""
    scd_account_uuid: str = ""
    scd_upstream_uuid: str = ""
    # The upstream's auth token, sent in X-SaaS-Domains-Auth-Token.
    proxy_auth_token: str = ""
    # The token on your webhook in the SaaS Custom Domains dashboard.
    scd_webhook_token: str = ""

    # Only for DOMAINS_PROVIDER=caddy: what customers point their DNS at.
    cname_target: str = "in.helpdock.app"
    server_ips: str = ""

    database_url: str = "sqlite:///data/app.db"


settings = Settings()
