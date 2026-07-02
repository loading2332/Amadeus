from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class HypothesisProvider(Protocol):
    async def generate(self, query: str, *, style: str) -> str: ...


@dataclass(frozen=True)
class LLMHypothesisProvider:
    provider: Any
    model: str | None = None

    async def generate(self, query: str, *, style: str) -> str:
        instruction = (
            "把查询改写成一条可能存在于历史记忆中的具体事件陈述。"
            if style == "event"
            else "把查询改写成一条语义完整、便于检索的用户事实陈述。"
        )
        response = await self.provider.chat(
            [
                {
                    "role": "user",
                    "content": f"{instruction}\n只输出陈述句，不要解释。\n查询：{query}",
                }
            ],
            model=self.model,
            max_tokens=80,
            tools=[],
            disable_thinking=True,
        )
        return str(response.content or "").strip()


@dataclass(frozen=True)
class OpenAIEmbeddingConfig:
    api_key: str
    model: str
    base_url: str | None = None
    timeout_seconds: float = 90


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        config: OpenAIEmbeddingConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self.config.model,
            input=text,
        )
        return list(response.data[0].embedding)
