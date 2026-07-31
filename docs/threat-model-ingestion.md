# Threat model — remote ingestion

Scope: fetching and indexing **third-party catalogs / docs** into front-design-mcp, then exposing them to AI agents via MCP tools. Complements [ADR 0004](adr/0004-untrusted-ingestion.md).

Status labels: **implemented** / **partial** / **not implemented**.

## Assets and trust boundaries

| Asset | Trust |
|-------|--------|
| Local fixtures under `data/fixtures/` | Repo-reviewed, still treated as untrusted *content* at sanitize time |
| Remote registry JSON (e.g. shadcn/magicui URLs) | **Untrusted input** |
| SQLite / Postgres store | Trusted as local state; content rows remain untrusted when served |
| Embedding API (`openai`) | Third party sees chunk/query text |
| MCP client / agent | Must not treat indexed prose as system instructions |
| `.env` / API keys | Secrets — never commit |

Boundary: anything crossing `fetch_json` / adapter online paths is hostile until sanitized. Offline fixtures skip the network but still go through the same sanitize helpers when building chunks.

## Prompt injection via indexed documentation

| Control | Status | Notes |
|---------|--------|-------|
| Strip control-like phrases | **Implemented** | `security/sanitize.py` regexes (ignore previous instructions, jailbreak, roleplay, etc.) |
| Length truncation | **Implemented** | Default summary max 8000; curated chunks ~1400 (`CHUNK_CONTENT_MAX`) |
| Untrusted marker on stored summaries | **Implemented** | Prefix `[UNTRUSTED_SOURCE_DATA]` via `mark_untrusted` |
| Marker on tool serialization | **Partial** | `chunk_to_dict` adds `[UNTRUSTED SOURCE DATA]` (wording differs slightly from the sanitize constant) and `untrusted: true` |
| Facts vs inferences in tool envelopes | **Implemented** | Compare/recommend/search paths separate `facts` / `inferences` (inferences often empty on raw hits) |
| Refuse to execute embedded instructions | **Partial** | Process never `eval`s chunk text; agent compliance depends on the client model following MCP instructions |

Residual risk: sanitized text can still nudge an agent. Markers and facts/inferences **limit** damage; they do not eliminate it.

## SSRF and outbound HTTP

Adapters that fetch online (e.g. shadcn, magicui) call `adapters/common.fetch_json`:

| Control | Status | Notes |
|---------|--------|-------|
| Network ingest off by default | **Implemented** | `FRONT_DESIGN_ENABLE_NETWORK_INGEST=false`; CLI exits **2** if `--online` without the flag (same code as `SyncOutcome.PARTIAL`); pipeline raises if online requested while disabled |
| Fixed registry URLs in adapters | **Partial** | Current adapters use hardcoded HTTPS registry URLs — not arbitrary user URLs — but there is **no shared allowlist helper** |
| Host allowlist | **Not implemented** | Gap: any future adapter that takes a URL could hit internal hosts |
| Block private / link-local / metadata IPs | **Not implemented** | Gap: no IP-range checks before connect |
| Redirect policy | **Partial / weak** | `httpx.Client(..., follow_redirects=True)` — redirects **are followed** with **no** re-validation of the final host |
| HTTPS-only enforcement | **Not implemented** | Relies on adapter authors hardcoding `https://` |
| DNS rebinding defenses | **Not implemented** | |

**Recommendation (gap):** centralize fetch behind a helper that allowlists hosts, disables or re-checks redirects, and rejects private/link-local/metadata ranges (including after redirect).

## Response size, time, decompression, content type

| Control | Status | Notes |
|---------|--------|-------|
| HTTP timeout | **Implemented** | `FRONT_DESIGN_HTTP_TIMEOUT` (default 30s) applied to adapters that expose `http_timeout`; `fetch_json` default 30s |
| Retries with backoff | **Implemented** | `fetch_json`: 3 attempts, exponential backoff |
| Max response body size | **Not implemented** | Relies on httpx defaults / memory pressure |
| Content-Type allowlist | **Not implemented** | `response.json()` only — wrong types fail parse, but no explicit allowlist |
| Compression bomb limits | **Not implemented** | httpx may decompress; no app-level cap |

## Licence / redistribution

| Control | Status | Notes |
|---------|--------|-------|
| Per-source `LicenseInfo` | **Implemented** | SPDX / name / redistributable / notes on adapters |
| GSAP metadata-only | **Implemented** | `redistributable=False`; curated metadata fixtures; license note in adapter |
| Automated licence scanning of payloads | **Not implemented** | Policy is adapter-author diligence |
| Enforce non-redistributable at store write | **Not implemented** | Flag is metadata for consumers; store does not block large bodies by licence |

## Secrets exposure

| Control | Status | Notes |
|---------|--------|-------|
| `.env` gitignored | **Implemented** | `.gitignore` includes `.env` |
| DB URL redaction helper | **Implemented** | `Settings.redacted_database_url()` |
| Embedding API key as `SecretStr` + scrub in errors/`repr` | **Implemented** | OpenAI provider |
| Secrets in MCP tool responses | **Partial** | Tools do not intentionally return keys; no systematic secret-scanning of chunk text |

## Supply chain

| Control | Status | Notes |
|---------|--------|-------|
| Locked dependencies | **Implemented** | `uv.lock` pinned; CI uses `uv sync --frozen` |
| Vendored `.agents/skills` tree | **Partial** | Present for authoring guidance; not a runtime dependency of the server — treat as untrusted third-party docs if executed by agents |
| Signed releases / SLSA | **Not implemented** | |
| Runtime integrity checks of fixtures | **Not implemented** | Fixtures trusted as repo content |

## Prioritised gap list

1. **SSRF hardening** for any online fetch (allowlist, no blind redirects, block private ranges) — highest priority before expanding network ingest.
2. **Response size / content-type caps** on `fetch_json`.
3. **Unify untrusted markers** (`[UNTRUSTED_SOURCE_DATA]` vs `[UNTRUSTED SOURCE DATA]`).
4. **Licence enforcement hooks** if adapters ever store more than short summaries.
5. Document and keep network ingest **opt-in** (already default-off — preserve that).

Do not claim mitigations that are absent. This document’s value is accuracy over reassurance.
