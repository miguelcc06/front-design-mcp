"""Unit tests for Reciprocal Rank Fusion — pure, no I/O."""

from __future__ import annotations

import random

import pytest

from front_design_mcp.search.base import RankedChunk
from front_design_mcp.search.rrf import DEFAULT_K, as_fused, reciprocal_rank_fusion


def test_exact_fused_score_for_hand_built_case() -> None:
    lexical = [
        RankedChunk(chunk_id="a", score=10.0, rank=1),
        RankedChunk(chunk_id="b", score=5.0, rank=2),
    ]
    vector = [
        RankedChunk(chunk_id="a", score=0.9, rank=1),
        RankedChunk(chunk_id="c", score=0.8, rank=2),
    ]
    k = 60
    fused = reciprocal_rank_fusion(lexical, vector, k=k)
    by_id = {c.chunk_id: c for c in fused}

    assert by_id["a"].score == pytest.approx(1.0 / (k + 1) + 1.0 / (k + 1))
    assert by_id["b"].score == pytest.approx(1.0 / (k + 2))
    assert by_id["c"].score == pytest.approx(1.0 / (k + 2))
    assert fused[0].chunk_id == "a"


def test_both_branches_outrank_single_branch_despite_higher_raw_score() -> None:
    # Chunk "solo" has a huge raw BM25 score at rank 1 lexical-only.
    # Chunk "both" appears at rank 2 lexical and rank 1 vector — RRF should
    # prefer "both" because ranks fuse, not raw scores.
    lexical = [
        RankedChunk(chunk_id="solo", score=999.0, rank=1),
        RankedChunk(chunk_id="both", score=1.0, rank=2),
    ]
    vector = [
        RankedChunk(chunk_id="both", score=0.1, rank=1),
    ]
    fused = reciprocal_rank_fusion(lexical, vector, k=60)
    assert fused[0].chunk_id == "both"
    assert fused[1].chunk_id == "solo"
    assert fused[0].score > fused[1].score


def test_per_branch_ranks_and_scores_recorded() -> None:
    lexical = [RankedChunk(chunk_id="x", score=3.5, rank=2)]
    vector = [RankedChunk(chunk_id="x", score=0.77, rank=1)]
    fused = reciprocal_rank_fusion(lexical, vector)
    assert len(fused) == 1
    c = fused[0]
    assert c.lexical_rank == 2
    assert c.lexical_score == 3.5
    assert c.vector_rank == 1
    assert c.vector_score == 0.77


def test_sorted_descending_with_chunk_id_tiebreak_and_deterministic() -> None:
    # Equal fused scores → deterministic tie-break by chunk_id ascending.
    lexical = [
        RankedChunk(chunk_id="m", score=1.0, rank=1),
        RankedChunk(chunk_id="b", score=1.0, rank=2),
    ]
    vector = [
        RankedChunk(chunk_id="b", score=0.5, rank=1),
        RankedChunk(chunk_id="m", score=0.5, rank=2),
    ]
    first = reciprocal_rank_fusion(lexical, vector, k=10)
    assert first[0].score == pytest.approx(first[1].score)
    assert [c.chunk_id for c in first] == ["b", "m"]

    for _ in range(20):
        lex = list(lexical)
        vec = list(vector)
        random.shuffle(lex)
        random.shuffle(vec)
        again = reciprocal_rank_fusion(lex, vec, k=10)
        assert [c.chunk_id for c in again] == ["b", "m"]
        assert [c.score for c in again] == pytest.approx([c.score for c in first])


def test_empty_lexical_preserves_vector_ordering() -> None:
    vector = [
        RankedChunk(chunk_id="v1", score=0.9, rank=1),
        RankedChunk(chunk_id="v2", score=0.5, rank=2),
        RankedChunk(chunk_id="v3", score=0.1, rank=3),
    ]
    fused = reciprocal_rank_fusion([], vector, k=60)
    assert [c.chunk_id for c in fused] == ["v1", "v2", "v3"]
    assert all(c.lexical_rank is None for c in fused)
    assert fused[0].score == pytest.approx(1.0 / (60 + 1))


def test_both_branches_empty_returns_empty() -> None:
    assert reciprocal_rank_fusion([], []) == []


def test_small_k_emphasises_top_ranks_more() -> None:
    # shallow: weight/(k+1); deep: 2*weight/(k+5).
    # Small k favours the top-ranked shallow hit; large k lets deep's dual
    # contribution overtake.
    lexical = [
        RankedChunk(chunk_id="deep", score=1.0, rank=5),
        RankedChunk(chunk_id="shallow", score=0.9, rank=1),
    ]
    vector = [
        RankedChunk(chunk_id="deep", score=0.5, rank=5),
    ]
    at_small = reciprocal_rank_fusion(lexical, vector, k=1)
    at_large = reciprocal_rank_fusion(lexical, vector, k=60)
    assert at_small[0].chunk_id == "shallow"
    assert at_large[0].chunk_id == "deep"
    assert DEFAULT_K == 60


def test_asymmetric_weights_zero_removes_contribution_but_records_rank() -> None:
    lexical = [RankedChunk(chunk_id="a", score=5.0, rank=1)]
    vector = [RankedChunk(chunk_id="a", score=0.9, rank=2)]
    fused = reciprocal_rank_fusion(
        lexical, vector, k=10, lexical_weight=1.0, vector_weight=0.0
    )
    assert len(fused) == 1
    c = fused[0]
    assert c.score == pytest.approx(1.0 / (10 + 1))
    assert c.lexical_rank == 1
    assert c.vector_rank == 2
    assert c.vector_score == 0.9


def test_k_less_than_one_raises() -> None:
    with pytest.raises(ValueError, match="RRF k must be >= 1"):
        reciprocal_rank_fusion([], [], k=0)
    with pytest.raises(ValueError, match="RRF k must be >= 1"):
        reciprocal_rank_fusion([], [], k=-5)


def test_as_fused_sets_only_relevant_branch_and_preserves_score() -> None:
    branch = [
        RankedChunk(chunk_id="c1", score=4.25, rank=1),
        RankedChunk(chunk_id="c2", score=1.5, rank=2),
    ]
    lex = as_fused(branch, lexical=True)
    assert lex[0].score == 4.25
    assert lex[0].lexical_rank == 1
    assert lex[0].lexical_score == 4.25
    assert lex[0].vector_rank is None
    assert lex[0].vector_score is None

    vec = as_fused(branch, lexical=False)
    assert vec[1].score == 1.5
    assert vec[1].vector_rank == 2
    assert vec[1].vector_score == 1.5
    assert vec[1].lexical_rank is None
    assert vec[1].lexical_score is None
