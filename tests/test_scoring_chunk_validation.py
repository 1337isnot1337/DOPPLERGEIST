"""Pure configuration tests; do not generate or score synthetic recordings."""

import pytest

from dopplergeist.pipeline import _validated_scoring_chunk, score_chunks


@pytest.mark.parametrize("chunk", [1, 2, 64])
def test_valid_scoring_chunks(chunk):
    assert _validated_scoring_chunk(chunk) == chunk


@pytest.mark.parametrize("chunk", [0, -1, True, False, 1.5, "8", None])
def test_invalid_scoring_chunk_fails_before_scoring(chunk):
    # A nonempty candidate list must never turn into a successful, empty ranking.
    with pytest.raises(ValueError, match="scoring_chunk must be a positive integer"):
        score_chunks([object()], chunk, 1, {})
