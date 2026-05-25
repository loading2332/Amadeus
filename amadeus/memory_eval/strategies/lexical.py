from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts import CommonEvalCase, MemoryArtifact, MemoryEvalGroup, MemoryStrategyResult


_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _IndexedArtifact:
    artifact: MemoryArtifact
    tokens: frozenset[str]


class LexicalMemoryStrategy:
    strategy_name = "lexical"

    def __init__(self, *, top_k: int = 5) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        self.top_k = top_k
        self._prepared_group_id = ""
        self._index: tuple[_IndexedArtifact, ...] = ()

    def prepare_group(self, group: MemoryEvalGroup) -> None:
        self._prepared_group_id = group.group_id
        self._index = tuple(
            _IndexedArtifact(artifact=artifact, tokens=_tokens(artifact.text))
            for artifact in group.memory_artifacts
        )

    def run(self, case: CommonEvalCase) -> MemoryStrategyResult:
        if not self._index and case.memory_artifacts:
            self._prepared_group_id = case.group_id
            self._index = tuple(
                _IndexedArtifact(artifact=artifact, tokens=_tokens(artifact.text))
                for artifact in case.memory_artifacts
            )

        query_tokens = _tokens(case.query)
        ranked = sorted(
            (
                (_overlap_score(query_tokens, item.tokens), item.artifact)
                for item in self._index
            ),
            key=lambda item: (-item[0], item[1].artifact_id),
        )
        selected = [(score, artifact) for score, artifact in ranked if score > 0][: self.top_k]
        selected_ids = tuple(artifact.artifact_id for _, artifact in selected)

        return MemoryStrategyResult(
            retrieved_memory_ids=selected_ids,
            retrieval_scores={artifact.artifact_id: score for score, artifact in selected},
            injected_memory_ids=selected_ids,
            injected_context="\n".join(artifact.text for _, artifact in selected),
            trace={
                "prepared_group_id": self._prepared_group_id,
                "query_token_count": len(query_tokens),
                "indexed_artifact_count": len(self._index),
            },
        )


def _tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(0) for match in _TOKEN_RE.finditer(text.lower()))


def _overlap_score(query_tokens: frozenset[str], artifact_tokens: frozenset[str]) -> float:
    if not query_tokens or not artifact_tokens:
        return 0.0
    return len(query_tokens & artifact_tokens) / len(query_tokens)
