"""Search service — load chunks from store and run filtered BM25 search."""

from __future__ import annotations

from front_design_mcp.models import Citation, DocumentationChunk, FrontendResource, SearchHit
from front_design_mcp.search.lexical import LexicalBM25Index
from front_design_mcp.store.sqlite_store import SqliteStore


class SearchService:
    """Lexical BM25 search over store chunks with optional resource filters."""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store
        self._index = LexicalBM25Index()
        self._chunk_by_id: dict[str, DocumentationChunk] = {}
        self._resource_by_id: dict[str, FrontendResource] = {}

    def rebuild(self) -> int:
        """Rebuild BM25 from all chunks currently in the store. Returns chunk count."""
        # High limits for v1 corpus size
        chunks = self._store.list_chunks(limit=50_000)
        resources = self._store.list_resources(limit=50_000)
        self._chunk_by_id = {c.id: c for c in chunks}
        self._resource_by_id = {r.id: r for r in resources}
        self._index.rebuild(chunks)
        return len(chunks)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        source_id: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
    ) -> list[SearchHit]:
        """Search chunks; attach matching resources and apply filters."""
        if not self._chunk_by_id:
            self.rebuild()

        # Over-fetch then filter (small corpus)
        raw_hits = self._index.search(query, limit=max(limit * 5, 50))
        results: list[SearchHit] = []
        tag_set = {t.lower() for t in tags} if tags else None

        for hit in raw_hits:
            chunk = hit.chunk
            if chunk is None:
                continue
            resource = self._resource_by_id.get(chunk.resource_id) or self._store.get_resource(
                chunk.resource_id
            )
            if resource is None:
                continue
            if source_id and resource.source.source_id != source_id:
                continue
            if kind and resource.kind.value != kind:
                continue
            if tag_set:
                resource_tags = {t.lower() for t in resource.tags}
                chunk_tags = {t.lower() for t in chunk.tags}
                if not tag_set.intersection(resource_tags | chunk_tags):
                    continue

            citation = hit.citation or Citation(
                resource_id=resource.id,
                chunk_id=chunk.id,
                title=chunk.title,
                url=chunk.source_url or resource.docs_url,
                source_id=resource.source.source_id,
                excerpt=chunk.content[:240] if chunk.content else None,
            )
            if citation.source_id is None:
                citation = citation.model_copy(
                    update={"source_id": resource.source.source_id}
                )

            results.append(
                SearchHit(
                    resource=resource,
                    chunk=chunk,
                    score=hit.score,
                    citation=citation,
                    facts=hit.facts
                    + [
                        f"source={resource.source.source_id}",
                        f"kind={resource.kind.value}",
                    ],
                    inferences=[],
                )
            )
            if len(results) >= limit:
                break
        return results


__all__ = ["SearchService"]
