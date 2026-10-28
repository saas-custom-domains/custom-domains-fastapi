import hmac
import re

from app.settings import settings

_PORT = re.compile(r":\d+$")
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalize_host(value: str) -> str:
    """'Help.Acme.com.' and 'help.acme.com:443' are the same host."""
    return _PORT.sub("", value.strip().lower()).removesuffix(".")


def is_valid_host(host: str) -> bool:
    labels = host.split(".")
    return (
        len(host) <= 253
        and len(labels) >= 2
        and all(_LABEL.match(label) for label in labels)
    )


def app_hosts() -> list[str]:
    hosts = (normalize_host(h) for h in settings.app_hosts.split(","))
    return [h for h in hosts if h]


def is_app_host(host: str) -> bool:
    return host in app_hosts()


def is_reserved_host(host: str) -> bool:
    if is_app_host(host):
        return True
    domain = normalize_host(settings.app_domain)
    return bool(domain) and (host == domain or host.endswith(f".{domain}"))


def secure_compare(given: str, expected: str) -> bool:
    """Constant-time comparison, so a wrong guess doesn't reveal how many
    leading characters were right."""
    return hmac.compare_digest(given.encode(), expected.encode())
