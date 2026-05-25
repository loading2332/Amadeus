from __future__ import annotations

from ..contracts import CommonEvalCase, MemoryStrategyResult


class NoopMemoryStrategy:
    strategy_name = "noop"

    def run(self, case: CommonEvalCase) -> MemoryStrategyResult:
        return MemoryStrategyResult(
            trace={
                "strategy_name": self.strategy_name,
                "artifact_count": len(case.memory_artifacts),
                "omitted_reason": "noop_strategy",
            }
        )

