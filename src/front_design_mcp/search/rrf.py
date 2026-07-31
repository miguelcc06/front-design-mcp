"""Reciprocal Rank Fusion.

BM25 scores, ``ts_rank_cd`` scores and cosine similarities live on incompatible
scales, so they are never added together. RRF combines *ranks* instead, which is
scale-free: each branch contributes ``weight / (k + rank)``.
"""

from __future__ import annotations

from collections.abc import Sequence

from front_design_mcp.search.base import FusedCandidate, RankedChunk

DEFAULT_K = 60


def reciprocal_rank_fusion(
    lexical: Sequence[RankedChunk],
    vector: Sequence[RankedChunk],
    *,
    k: int = DEFAULT_K,
    lexical_weight: float = 1.0,
    vector_weight: float = 1.0,
) -> list[FusedCandidate]:
    """Fuse two ranked lists into one, highest fused score first.

    ``k`` dampens the influence of top ranks; the conventional value is 60. Ties
    are broken by chunk id so results are deterministic. Passing an empty list
    for a branch is valid and yields the other branch's ordering (with fused
    scores, not the branch's raw scores).
    """
    if k < 1:
        raise ValueError(f"RRF k must be >= 1, got {k}")

    fused: dict[str, FusedCandidate] = {}

    for ranked in lexical:
        candidate = fused.setdefault(ranked.chunk_id, FusedCandidate(chunk_id=ranked.chunk_id))
        candidate.lexical_rank = ranked.rank
        candidate.lexical_score = ranked.score
        candidate.score += lexical_weight / (k + ranked.rank)

    for ranked in vector:
        candidate = fused.setdefault(ranked.chunk_id, FusedCandidate(chunk_id=ranked.chunk_id))
        candidate.vector_rank = ranked.rank
        candidate.vector_score = ranked.score
        candidate.score += vector_weight / (k + ranked.rank)

    return sorted(fused.values(), key=lambda c: (-c.score, c.chunk_id))


def as_fused(branch: Sequence[RankedChunk], *, lexical: bool) -> list[FusedCandidate]:
    """Wrap a single branch's results in :class:`FusedCandidate` without fusing.

    Keeps the single-branch path and the hybrid path returning the same shape.
    The branch's own score is preserved as ``score`` because no fusion happened.
    """
    out: list[FusedCandidate] = []
    for ranked in branch:
        candidate = FusedCandidate(chunk_id=ranked.chunk_id, score=ranked.score)
        if lexical:
            candidate.lexical_rank = ranked.rank
            candidate.lexical_score = ranked.score
        else:
            candidate.vector_rank = ranked.rank
            candidate.vector_score = ranked.score
        out.append(candidate)
    return out


__all__ = ["DEFAULT_K", "as_fused", "reciprocal_rank_fusion"]
