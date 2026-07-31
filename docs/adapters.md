# Adding a SourceAdapter

How to plug a new frontend catalog into front-design-mcp (offline-first).

## 1. Contract

Implement `SourceAdapter` in `src/front_design_mcp/adapters/base.py`:

| Member | Purpose |
|--------|---------|
| `source_id` | Stable registry key (e.g. `motion`) |
| `source_ref` | Homepage, attribution, optional registry URL |
| `license_info` | Default `LicenseInfo` (SPDX, redistributable flag, notes) |
| `fetch_catalog(*, offline)` | Raw list of dicts (fixtures when offline) |
| `fetch_details(item_id, *, offline)` | Single raw item |
| `normalize(raw)` | → `FrontendResource` with id `{source_id}:{local_id}` |

Optional: `build_chunks(resource) -> list[DocumentationChunk]` for curated summaries. If omitted, ingest uses `make_chunks_for_resource` from `adapters/common.py`.

## 2. Fixtures

Create `data/fixtures/{source_id}/` with JSON the adapter can parse offline. Prefer small curated catalogs over HTML scrapes. Mark untrusted docs at ingest (`sanitize_summary(..., mark=True)`).

## 3. Register

1. Add the class under `src/front_design_mcp/adapters/{source_id}.py`.
2. Append `source_id` to `ADAPTER_SOURCE_IDS` and a branch in `get_adapter_class` (`adapters/__init__.py`).
3. Ensure the ingest CLI discovers it via the registry (`front-design-ingest --offline`).

## 4. Helpers

Use `adapters/common.py`:

- `load_fixture_dict` / `load_fixture_list` — typed fixture loaders
- `fetch_json` — online GET with retries (only when network ingest is enabled)
- `sanitize_text` / `make_chunks_for_resource` — untrusted text + 1–3 chunks
- `find_by_id` — lookup in raw catalogs

## 5. License notes

- MIT/Apache sources: index metadata + short summaries; keep attribution.
- Non-redistributable (e.g. GSAP Standard No Charge): metadata only, `redistributable=False`, never vendor library source.

## 6. Validate

```bash
uv run front-design-ingest --offline --source {source_id}
uv run pytest -q tests/test_adapters_offline.py
uv run python scripts/mcp_smoke.py
```

Update `docs/research.md` / ADRs if the source choice is architectural.
