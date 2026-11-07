# Backup address lookup for the Worker

Date: 2026-11-07 · Status: approved by Yoshi in chat ("Approve and build") · Size: small

## Intent
On Yoshi's iPhone hotspot the carrier's DNS refuses every `*.workers.dev` name, so Clicky reports "couldn't reach the
Clicky Worker" even though the Worker is up and reachable directly. Clicky should work on such networks without
changing Windows settings.

## Design (approved)
- Only when the system lookup of the **Worker's host** fails (`socket.gaierror`), Clicky asks DNS-over-HTTPS:
  Cloudflare `https://1.1.1.1/dns-query`, then Google `https://8.8.8.8/resolve`, contacted by IP so the blocked lookup
  can't stop them. Clicky then connects to the returned address; TLS still verifies the Worker's real hostname.
- Every other host uses the system lookup unchanged; normal networks see no change or delay.
- Answers are cached for 5 minutes.
- If the backup lookup fails too, the original error stands ("couldn't reach the Clicky Worker").
- Implemented as a scoped wrapper around `socket.getaddrinfo` (asyncio resolves through it), installed once at
  startup for the Worker host.

## Approaches considered
1. **Scoped `getaddrinfo` fallback (chosen):** one place covers every Worker route (token, chat, TTS); small.
2. Custom httpx/httpcore transport with its own resolver: more code for the same effect.
3. Move the Worker to a custom domain: costs a domain and Cloudflare setup, and may be blocked too.

## Non-goals
Changing Windows DNS settings; a fallback for other hosts (AssemblyAI, etc.).
