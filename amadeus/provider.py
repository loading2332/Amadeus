from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeGuard

from openai import AsyncOpenAI

from amadeus.context import Message


class ContextLengthError(RuntimeError):
    pass


class ContentSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMProviderConfig:
    api_key: str
    model: str
    base_url: str | None = None
    timeout_seconds: float = 90
    max_tokens: int = 2048


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    raw: Any = None
    model: str | None = None
    response_id: str | None = None
    usage: Mapping[str, Any] | None = None


class ChatCompletionsClient(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class ChatNamespace(Protocol):
    completions: ChatCompletionsClient


class ChatClient(Protocol):
    chat: ChatNamespace


class _HasModelDump(Protocol):
    def model_dump(self) -> Mapping[str, Any]: ...


class LLMProvider:
    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        client: ChatClient | None = None,
    ) -> None:
        self.config = config
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if not callable(close):
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def chat(
        self,
        messages: list[Message] | list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        disable_thinking: bool = False,
        **request_options: Any,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            **request_options,
        }
        if tools:
            payload["tools"] = tools
        if disable_thinking:
            extra_body = dict(payload.get("extra_body") or {})
            extra_body.setdefault("enable_thinking", False)
            payload["extra_body"] = extra_body

        try:
            raw = await self._client.chat.completions.create(**payload)
        except Exception as error:
            message = str(error)
            lowered = message.lower()
            if "context_length" in lowered or "maximum context" in lowered:
                raise ContextLengthError(message) from error
            if "content_filter" in lowered or "content policy" in lowered:
                raise ContentSafetyError(message) from error
            raise

        choice = raw.choices[0] if getattr(raw, "choices", None) else None
        assistant_message = getattr(choice, "message", None)
        content = getattr(assistant_message, "content", None)
        parsed_content = content if isinstance(content, str) else None
        tool_calls = _extract_tool_calls(assistant_message)
        if parsed_content is None and not tool_calls:
            raise ValueError("LLM response did not include assistant content")

        usage = getattr(raw, "usage", None)
        usage_payload = _usage_payload(usage)
        return LLMResponse(
            content=parsed_content,
            tool_calls=tool_calls,
            raw=raw,
            model=getattr(raw, "model", None),
            response_id=getattr(raw, "id", None),
            usage=usage_payload,
        )


def _extract_tool_calls(message: Any) -> list[LLMToolCall]:
    raw_tool_calls = getattr(message, "tool_calls", None) or []
    parsed: list[LLMToolCall] = []
    for item in raw_tool_calls:
        function = getattr(item, "function", None)
        if function is None:
            continue
        parsed.append(
            LLMToolCall(
                id=str(getattr(item, "id", "") or ""),
                name=str(getattr(function, "name", "") or ""),
                arguments=_parse_tool_call_arguments(
                    getattr(function, "arguments", None)
                ),
            )
        )
    return parsed


def _parse_tool_call_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        payload = arguments.strip()
        if not payload:
            return {}
        loaded = json.loads(payload)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _has_model_dump(value: object) -> TypeGuard[_HasModelDump]:
    return hasattr(value, "model_dump")


def _usage_payload(usage: object) -> Mapping[str, Any] | None:
    if _has_model_dump(usage):
        return usage.model_dump()
    if isinstance(usage, Mapping):
        return usage
    return None
