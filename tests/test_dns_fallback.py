import socket

import httpx
import pytest

from clicky import dns_fallback

WORKER = "clicky-proxy.example.workers.dev"


@pytest.fixture
def fake_system(monkeypatch):
    """A system resolver that knows only example.com, and restores socket.getaddrinfo afterwards."""
    calls = []

    def system_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        calls.append(host)
        if host == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(socket, "getaddrinfo", system_getaddrinfo)
    monkeypatch.setattr(dns_fallback, "_installed", None)
    dns_fallback.clear_cache()
    return calls


def test_system_lookup_is_used_when_it_works(fake_system):
    resolved = []
    dns_fallback.install_dns_fallback(["example.com"], resolve=lambda host: resolved.append(host) or ["1.2.3.4"])
    assert socket.getaddrinfo("example.com", 443)[0][4] == ("93.184.216.34", 443)
    assert resolved == []


def test_a_failed_lookup_of_the_worker_falls_back_to_dns_over_https(fake_system):
    dns_fallback.install_dns_fallback([WORKER.upper()], resolve=lambda host: ["104.21.0.1", "172.67.0.1"])
    answers = socket.getaddrinfo(WORKER, 443, 0, socket.SOCK_STREAM)
    assert [answer[4] for answer in answers] == [("104.21.0.1", 443), ("172.67.0.1", 443)]
    assert answers[0][0] == socket.AF_INET and answers[0][1] == socket.SOCK_STREAM
    assert socket.getaddrinfo(WORKER, "443")[0][4] == ("104.21.0.1", 443)  # numeric-string port
    assert socket.getaddrinfo(WORKER, None)[0][4] == ("104.21.0.1", 0)


def test_other_hosts_are_left_alone(fake_system):
    dns_fallback.install_dns_fallback([WORKER], resolve=lambda host: ["104.21.0.1"])
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("blocked.example.org", 443)


def test_answers_are_cached(fake_system):
    resolved = []
    dns_fallback.install_dns_fallback([WORKER], resolve=lambda host: resolved.append(host) or ["104.21.0.1"])
    socket.getaddrinfo(WORKER, 443)
    socket.getaddrinfo(WORKER, 443)
    assert resolved == [WORKER]


def test_if_the_backup_fails_the_original_error_stands(fake_system):
    def broken(host):
        raise httpx.ConnectError("no internet")

    dns_fallback.install_dns_fallback([WORKER], resolve=broken)
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo(WORKER, 443)
    dns_fallback.install_dns_fallback([WORKER], resolve=lambda host: [])
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo(WORKER, 443)


def test_installing_twice_wraps_once(fake_system):
    dns_fallback.install_dns_fallback([WORKER], resolve=lambda host: ["104.21.0.1"])
    dns_fallback.install_dns_fallback([WORKER], resolve=lambda host: ["104.21.0.2"])
    socket.getaddrinfo("example.com", 443)
    assert fake_system == ["example.com"]  # the system resolver was called once, not through two wrappers
    assert socket.getaddrinfo(WORKER, 443)[0][4] == ("104.21.0.2", 443)  # the newest settings win


def test_resolve_over_https_reads_a_records_and_tries_the_next_resolver():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "1.1.1.1":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"Status": 0, "Answer": [{"type": 5, "data": "alias."}, {"type": 1, "data": "104.21.0.1"}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert dns_fallback.resolve_over_https(WORKER, client=client) == ["104.21.0.1"]
    assert seen == ["1.1.1.1", "8.8.8.8"]
