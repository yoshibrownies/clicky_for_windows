# Backup Worker address lookup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the network's DNS can't resolve the Worker host, resolve it over DNS-over-HTTPS and connect anyway.

**Architecture:** `clicky/dns_fallback.py` wraps `socket.getaddrinfo` for an allow-list of hostnames; on `gaierror` it asks DoH resolvers (by IP), caches the answer and returns addrinfo tuples for it. `app.run` installs it for the Worker host.

**Tech Stack:** Python 3.13, httpx (sync client for DoH), pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-worker-dns-fallback-design.md`

## Global Constraints
- Only the Worker host; system lookup first; 5-minute cache; resolvers `https://1.1.1.1/dns-query` then `https://8.8.8.8/resolve`.
- No new dependencies; never log the Worker URL.

## Review Focus
- Installing twice must not wrap twice.
- Resolver returning no A records, bad JSON, or timing out → original gaierror re-raised.
- Port given as int, numeric string or None.
- Case-insensitive hostname match.
- Concurrent lookups from asyncio's executor threads (cache is shared).

---

### Task 1: dns_fallback module, wired into the app

**Files:** Create `clicky/dns_fallback.py`, `tests/test_dns_fallback.py`; modify `clicky/app.py` (after settings load).

**Interfaces — Produces:**
- `resolve_over_https(hostname: str, client: httpx.Client | None = None) -> list[str]` (IPv4 addresses, [] if none).
- `install_dns_fallback(hostnames: Iterable[str], resolve: Callable[[str], list[str]] = resolve_over_https) -> None`.
- `CACHE_SECONDS = 300`, `DOH_RESOLVERS` tuple of URLs.

- [ ] Tests: `test_system_lookup_is_used_when_it_works`; `test_a_failed_lookup_of_the_worker_falls_back_to_dns_over_https`
  (addrinfo ip + port); `test_other_hosts_are_left_alone` (gaierror still raised); `test_answers_are_cached`
  (resolver called once for two lookups); `test_if_the_backup_fails_the_original_error_stands`;
  `test_installing_twice_wraps_once`; `test_resolve_over_https_reads_a_records` (MockTransport, tries Google after
  Cloudflare fails).
- [ ] Run → FAIL; implement; run → PASS.
- [ ] Wire: `install_dns_fallback([urlparse(settings.worker_base_url).hostname])` after `load_settings`. AGENTS.md line.
- [ ] Live check on the hotspot: the network check script reaches `/transcribe-token`.
- [ ] Commit `fix: look up the Worker over DNS-over-HTTPS when the network's DNS refuses it`.
