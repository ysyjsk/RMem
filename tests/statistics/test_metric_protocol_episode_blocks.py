from __future__ import annotations

from pathlib import Path


def test_metric_protocol_declares_episode_level_permutation_blocks() -> None:
    text = Path("protocol/metric_spec_v1.md").read_text()
    assert "paired permutation over episode blocks" in text
    assert "averaged into one canonical_balanced - left_deep difference" in text
    assert "episode x replicate blocks" not in text
