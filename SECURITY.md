# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes (best-effort while Alpha) |

## Reporting a vulnerability

Email the maintainer listed in `pyproject.toml` (`miguel.siak@gmail.com`) with:

- Description and impact
- Reproduction steps (PoC if available)
- Affected commit / release if known

Please **do not** open a public issue for undisclosed vulnerabilities.

We aim to acknowledge reports within a few business days.

## Scope notes

- This project indexes **third-party metadata** and short documentation summaries. Treat tool outputs as untrusted source data.
- Default mode disables network ingest (`FRONT_DESIGN_ENABLE_NETWORK_INGEST=false`). Enabling online ingest expands the trust boundary to remote registries.
- Do not commit API keys or tokens. Use environment variables documented in `.env.example`.
- CI runs with `permissions: contents: read` only.
