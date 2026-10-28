"""Runs against `docker compose up`.

The browser sends every request for a customer domain (*.test) to the
mock proxy, the way DNS sends a real customer domain to SaaS Custom
Domains. Host stays "acme.test" whatever port the mock listens on, so
several stacks can run side by side.
"""

import os

import httpx2
import pytest

APP_URL = f"http://localhost:{os.environ.get('APP_PORT', '3000')}"
PROXY_URL = (
    f"http://127.0.0.1:{os.environ.get('SCD_MOCK_PROXY_PORT', '80')}"
)


@pytest.fixture(scope="session")
def base_url():
    return APP_URL


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    return {
        **browser_type_launch_args,
        "proxy": {"server": PROXY_URL, "bypass": "localhost"},
    }


@pytest.fixture
def app():
    """Requests straight to the app, skipping the proxy."""
    with httpx2.Client(base_url=APP_URL) as client:
        yield client


@pytest.fixture
def customer():
    """Requests for customer domains, through the mock proxy."""
    with httpx2.Client(proxy=PROXY_URL) as client:
        yield client
