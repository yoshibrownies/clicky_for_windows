"""A backup address lookup for the Worker, for networks whose DNS refuses `*.workers.dev` (some mobile carriers).

When the system lookup of an allow-listed host fails (or hasn't answered within SYSTEM_LOOKUP_BUDGET_SECONDS: a
refusing network can take ~12 s, longer than Clicky's 10 s connect timeout), the address is asked of DNS-over-HTTPS
resolvers contacted by IP (so the blocked lookup can't stop them). After that the system lookup is skipped for
CACHE_SECONDS and the remembered answer is used straight away. Clicky then connects to that address as usual; TLS still
checks the Worker's real hostname, so this is as safe as a normal connection. Every other host is untouched.
Installed as a thin wrapper around `socket.getaddrinfo`, which asyncio (and so httpx) resolves names through.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DOH_RESOLVERS = ("https://1.1.1.1/dns-query", "https://8.8.8.8/resolve")  # Cloudflare, then Google
DOH_TIMEOUT_SECONDS = 5.0
CACHE_SECONDS = 300.0
# Normal networks answer in milliseconds; a refusing one can take ~12 s. Past this, the backup is asked too.
SYSTEM_LOOKUP_BUDGET_SECONDS = 2.0

Resolver = Callable[[str], list[str]]


def resolve_over_https(hostname: str, client: httpx.Client | None = None) -> list[str]:
    """IPv4 addresses for `hostname` from the DNS-over-HTTPS resolvers, trying each in turn; [] if none answer."""
    own_client = client is None
    client = client or httpx.Client(timeout=DOH_TIMEOUT_SECONDS)
    try:
        for resolver_url in DOH_RESOLVERS:
            try:
                response = client.get(
                    resolver_url, params={"name": hostname, "type": "A"}, headers={"accept": "application/dns-json"}
                )
                response.raise_for_status()
                addresses = []
                for record in response.json().get("Answer") or []:
                    if isinstance(record, dict) and record.get("type") == 1:
                        try:
                            addresses.append(str(ipaddress.IPv4Address(str(record.get("data", "")))))
                        except ValueError:
                            continue
                if addresses:
                    return addresses
            except (httpx.HTTPError, ValueError, AttributeError) as resolver_error:
                logger.info("DNS-over-HTTPS resolver %s failed: %s", resolver_url, type(resolver_error).__name__)
        return []
    finally:
        if own_client:
            client.close()


@dataclass
class _Fallback:
    original: Callable
    hostnames: frozenset[str]
    resolve: Resolver
    wrapper: Callable | None = None


_installed: _Fallback | None = None
_cache: dict[str, tuple[float, list[str]]] = {}
_system_failed_until: dict[str, float] = {}  # hosts the network's DNS couldn't find, skipped until then
_cache_lock = threading.Lock()
_system_lookups = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="clicky-dns")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _system_failed_until.clear()


def _fresh_cached(hostname: str) -> list[str] | None:
    with _cache_lock:
        cached = _cache.get(hostname)
        return cached[1] if cached is not None and cached[0] > time.monotonic() else None


def _system_known_to_fail(hostname: str) -> bool:
    with _cache_lock:
        return _system_failed_until.get(hostname, 0.0) > time.monotonic()


def _remember_system_failed(hostname: str) -> None:
    with _cache_lock:
        _system_failed_until[hostname] = time.monotonic() + CACHE_SECONDS


def _normalise(hostname) -> str:
    if isinstance(hostname, bytes):
        hostname = hostname.decode("ascii", "ignore")
    return hostname.lower().rstrip(".") if isinstance(hostname, str) else ""


def _port_number(port) -> int:
    if isinstance(port, int):
        return port
    try:
        return int(port)
    except (TypeError, ValueError):
        return 0


def _backup_addresses(hostname: str, resolve: Resolver) -> list[str]:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(hostname)
        if cached is not None and cached[0] > now:
            return cached[1]
    try:
        addresses = resolve(hostname)
    except Exception as resolve_error:  # the backup failing must leave the original error in place
        logger.warning("Backup lookup of the Worker's address failed: %s", type(resolve_error).__name__)
        addresses = []
    if addresses:
        with _cache_lock:
            _cache[hostname] = (now + CACHE_SECONDS, addresses)
        logger.info("Network DNS couldn't find the Worker; using DNS-over-HTTPS instead")
    return addresses


def install_dns_fallback(hostnames: Iterable[str], resolve: Resolver = resolve_over_https) -> None:
    """Back up the system lookup of `hostnames` with DNS-over-HTTPS. Installing again updates the settings."""
    global _installed
    names = frozenset(name for name in (_normalise(host) for host in hostnames if host) if name)
    clear_cache()
    if _installed is not None and socket.getaddrinfo is _installed.wrapper:
        _installed.hostnames, _installed.resolve = names, resolve
        return
    state = _Fallback(original=socket.getaddrinfo, hostnames=names, resolve=resolve)

    def as_addrinfo(addresses: list[str], port, type, proto) -> list[tuple]:
        socket_type = type or socket.SOCK_STREAM
        protocol = proto or (socket.IPPROTO_TCP if socket_type == socket.SOCK_STREAM else 0)
        port_number = _port_number(port)
        return [(socket.AF_INET, socket_type, protocol, "", (address, port_number)) for address in addresses]

    def getaddrinfo_with_backup(host, port, family=0, type=0, proto=0, flags=0):
        name = _normalise(host)
        if name not in state.hostnames or family not in (0, socket.AF_INET):
            return state.original(host, port, family, type, proto, flags)
        # This network already failed to find it: use the remembered (or a fresh) backup answer straight away.
        if _system_known_to_fail(name):
            addresses = _fresh_cached(name) or _backup_addresses(name, state.resolve)
            if addresses:
                return as_addrinfo(addresses, port, type, proto)
            return state.original(host, port, family, type, proto, flags)
        # Give the network a short head start; past it (or on a refusal), ask the backup too.
        system_lookup = _system_lookups.submit(state.original, host, port, family, type, proto, flags)
        try:
            return system_lookup.result(timeout=SYSTEM_LOOKUP_BUDGET_SECONDS)
        except (socket.gaierror, concurrent.futures.TimeoutError):
            pass
        _remember_system_failed(name)
        addresses = _backup_addresses(name, state.resolve)
        if addresses:
            return as_addrinfo(addresses, port, type, proto)
        return system_lookup.result()  # no backup either: the network's own answer (or its error) stands

    state.wrapper = getaddrinfo_with_backup
    socket.getaddrinfo = getaddrinfo_with_backup
    _installed = state
