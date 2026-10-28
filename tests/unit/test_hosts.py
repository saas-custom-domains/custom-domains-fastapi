import pytest

from app.hosts import is_reserved_host, is_valid_host, normalize_host, secure_compare


def test_normalize_host():
    assert normalize_host(" Help.Acme.com.:443 ") == "help.acme.com"


@pytest.mark.parametrize(
    "host", ["help.acme.com", "acme.co.uk", "xn--bcher-kva.example"]
)
def test_valid_hosts(host):
    assert is_valid_host(host)


@pytest.mark.parametrize(
    "host", ["acme", "-acme.com", "acme..com", "ac me.com", "https://a.com", ""]
)
def test_invalid_hosts(host):
    assert not is_valid_host(host)


def test_reserved_hosts():
    assert is_reserved_host("helpdock.app")
    assert is_reserved_host("admin.helpdock.app")
    assert is_reserved_host("localhost")
    assert not is_reserved_host("nothelpdock.app")


def test_secure_compare():
    assert secure_compare("abc", "abc")
    assert not secure_compare("abd", "abc")
    assert not secure_compare("ab", "abc")
