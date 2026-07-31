# ADR 0001 — FastMCP stable 3.4.5

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

Necesitamos un servidor MCP en Python. El ecosistema ofrece FastMCP (framework de alto nivel) y el SDK bajo nivel `mcp`. FastMCP 4 existe como prerelease (`4.0.0b1`).

## Decision

Usar **FastMCP stable `3.4.5`** (`fastmcp==3.4.5`) con:

```python
from fastmcp import FastMCP
```

Explicitamente **no** usar:
- FastMCP 4 beta / prerelease
- `mcp.server.fastmcp` como import primario

## Consequences

- API estable documentada en https://gofastmcp.com y https://gofastmcp.com/llms.txt
- Pin exacto reduce sorpresas de breaking changes
- Licencia Apache-2.0 alineada con el proyecto
- Migración a v4 queda fuera de alcance de v1
