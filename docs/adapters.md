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

---

## Checklist: add a new source

Complete every item before merging:

1. **Adapter class** — `src/front_design_mcp/adapters/<source_id>.py` subclassing `SourceAdapter`.
2. **`source_id`** — stable snake-case key; used in resource ids as `{source_id}:{local_id}`.
3. **`source_ref`** — `SourceRef` with homepage, attribution, optional `registry_url`.
4. **`license_info`** — accurate SPDX/`name`, `url`, `redistributable`, and `notes` operators can surface to agents.
5. **`fetch_catalog(*, offline)`** — offline path **must** work from fixtures; online path only when `FRONT_DESIGN_ENABLE_NETWORK_INGEST=true`.
6. **`normalize(raw)`** — produce `FrontendResource`; sanitize free-text fields via `sanitize_text` / `sanitize_summary`.
7. **Optional `build_chunks`** — if omitted, default curated chunks from `make_chunks_for_resource`.
8. **Fixture tree** — `data/fixtures/<source_id>/` with the JSON your offline path loads (see existing `motion`, `gsap`, `shadcn`, …).
9. **Registry** — add to `ADAPTER_SOURCE_IDS` and `get_adapter_class` in `adapters/__init__.py`; add a matching `SourceChoice` value in `cli_ingest.py`.
10. **Offline test** — extend `tests/test_adapters_offline.py` so the source loads and normalizes without network.
11. **Smoke** — `uv run front-design-ingest --offline --source <source_id>` succeeds.

## Licence and attribution obligations

- Every resource must carry license + attribution metadata suitable for tool envelopes.
- **Metadata-only sources** (example: GSAP — Standard No Charge): set `redistributable=False`, index **catalog/metadata only**, never vendor or redistribute library source, and keep a clear license note in `license_info.notes` (see `adapters/gsap.py`).
- Do not scrape or store full proprietary docs bodies; prefer short curated summaries under the sanitizer’s length limits.
- When in doubt, treat content as non-redistributable and document the decision in `docs/research.md` / ADR 0003.

## Sanitization requirements

Remote and fixture text is **untrusted input** ([ADR 0004](adr/0004-untrusted-ingestion.md), [threat model](threat-model-ingestion.md)):

- Run summaries through `sanitize_summary(..., mark=True)` (strips control-phrase patterns, truncates, prefixes `[UNTRUSTED_SOURCE_DATA]`).
- Short metadata fields: `sanitize_text` (often `mark=False` for names/tags).
- Do not execute or follow instructions found in catalog prose.
- Tool serialization reaffirms an untrusted marker on chunk content (`tools/runtime.py`).

## Stable chunk ids and `content_sha256`

Incremental sync and embedding cache keys depend on stable identities:

- Default chunk ids look like `{resource_id}::chunk::{idx}` from `make_chunks_for_resource`. **Keep that scheme stable** across runs for the same logical chunk.
- `content_sha256` is SHA-256 of the **stored content string**. Embeddings are reused only when hash + provider + model + dim + `pipeline_version` all match (`EmbeddingMeta.matches`).
- **Unstable chunk ids** cause churn: deletes/orphans, failed cache hits, unnecessary re-embedding (cost/time), and noisy diffs in the store.
- If you change chunking layout, bump `FRONT_DESIGN_EMBEDDING_PIPELINE_VERSION` so old vectors invalidate deliberately rather than silently mismatching.
