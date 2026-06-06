from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from amadeus.context import ContextBuilder, ContextRenderResult, RuntimeContext
from amadeus.events import EventBus, TurnCommitted
from amadeus.provider import LLMProvider
from amadeus.response_parser import parse_response
from amadeus.session import SessionManager


@dataclass(frozen=True)
class PassiveTurnResult:
    session_key: str
    user_message_id: str
    assistant_message_id: str
    assistant_response: str
    context: ContextRenderResult
    provider_raw: Any = None


@dataclass
class PassiveRuntime:
    workspace_root: Path
    provider: LLMProvider
    session_manager: SessionManager
    event_bus: EventBus = field(default_factory=EventBus)
    context_builder: ContextBuilder = field(default_factory=ContextBuilder)
    history_window: int = 500

    async def run_turn(
        self,
        *,
        session_key: str,
        user_message: str,
        retrieved_memory: str | None = None,
        active_skills: list[str] | None = None,
        runtime_metadata: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> PassiveTurnResult:
        session = self.session_manager.get_or_create(session_key)
        history = session.get_history(self.history_window)
        context = RuntimeContext(
            workspace_root=self.workspace_root,
            history=history,
            current_user_message=user_message,
            retrieved_memory=retrieved_memory,
            active_skills=active_skills or [],
            runtime_metadata=runtime_metadata or {},
        )
        rendered = self.context_builder.render(context)
        response = await self.provider.chat(rendered.messages)
        parsed_response = parse_response(response.content, tool_chain=[])
        assistant_response = parsed_response.clean_text

        user_record = session.add_message("user", user_message, **(extra or {}))
        assistant_record = session.add_message("assistant", assistant_response)
        self.session_manager.save(session)
        await self.event_bus.emit(
            TurnCommitted(
                session_key=session_key,
                input_message=user_message,
                persisted_user_message=user_message,
                assistant_response=assistant_response,
                timestamp=datetime.now().astimezone(),
            )
        )
        return PassiveTurnResult(
            session_key=session_key,
            user_message_id=str(user_record["id"]),
            assistant_message_id=str(assistant_record["id"]),
            assistant_response=assistant_response,
            context=rendered,
            provider_raw=response.raw,
        )
