from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from psycopg import IntegrityError

from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.events import EventBus, TurnCommitted
from amadeus.memory.engine import MemoryEngine, MemoryWriteRequest
from amadeus.memory.source_refs import (
    build_entry_source_ref,
    parse_history_entry_happened_at,
)
from amadeus.provider import LLMProvider
from amadeus.session.store import Session, SessionManager, is_real_memory_message

_MARKER_PREFIX = "<!-- consolidation:"
_MARKER_SUFFIX = " -->"
_DATE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})")
_ALLOWED_PENDING_TAGS = {
    "identity",
    "preference",
    "key_info",
    "health_long_term",
    "requested_memory",
    "correction",
    "agent_context",
}


class MemoryChatProvider(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        disable_thinking: bool = False,
        **kwargs: Any,
    ) -> Any: ...


@dataclass(frozen=True)
class ConsolidateRequest:
    session: Session
    archive_all: bool = False
    force: bool = False


@dataclass(frozen=True)
class RefreshRecentTurnsRequest:
    session: Session


@dataclass
class ConsolidateResult:
    consolidated_count: int = 0
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ConsolidationWindow:
    old_messages: list[dict[str, Any]]
    consolidate_up_to: int


@dataclass(frozen=True)
class _ConsolidationDraft:
    window: _ConsolidationWindow
    source_ref: str
    history_entries: list[str]
    pending_items: str
    recent_context_text: str
    conversation: str
    archive_all: bool = False


class MarkdownMemoryStore:
    def __init__(
        self,
        workspace_root: str | Path,
        *,
        user_id: int = 1,
        db: PostgresDatabase | None = None,
        dsn: str | None = None,
    ) -> None:
        root = Path(workspace_root)
        self.memory_dir = root / "memory"
        self.journal_dir = self.memory_dir / "journal"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        self.memory_file = self.memory_dir / "MEMORY.md"
        self.self_file = self.memory_dir / "SELF.md"
        self.recent_context_file = self.memory_dir / "RECENT_CONTEXT.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.pending_file = self.memory_dir / "PENDING.md"
        self._lock = threading.Lock()
        self.user_id = int(user_id)
        if db is None:
            dsn_value = dsn or os.environ.get(
                "AMADEUS_POSTGRES_DSN",
                "postgresql://amadeus:amadeus@localhost:5432/amadeus",
            )
            db = PostgresDatabase(PostgresConfig(dsn=normalize_psycopg_dsn(dsn_value)))
            db.open()
            self._owns_db = True
        else:
            self._owns_db = False
        self.db = db

        for path in (
            self.memory_file,
            self.recent_context_file,
            self.history_file,
            self.pending_file,
        ):
            if not path.exists():
                path.touch()
        self._ensure_user()
        self._recover_pending_snapshot()

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def read_long_term(self) -> str:
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def backup_long_term(self, backup_name: str = "MEMORY.bak.md") -> None:
        if self.memory_file.exists():
            shutil.copyfile(self.memory_file, self.memory_file.with_name(backup_name))

    def read_self(self) -> str:
        return self.self_file.read_text(encoding="utf-8") if self.self_file.exists() else ""

    def write_self(self, content: str) -> None:
        self.self_file.write_text(content, encoding="utf-8")

    def read_recent_context(self) -> str:
        return self.recent_context_file.read_text(encoding="utf-8")

    def write_recent_context(self, content: str) -> None:
        self.recent_context_file.write_text(content, encoding="utf-8")

    def read_history(self, max_chars: int = 0) -> str:
        text = self._strip_markers(self.history_file.read_text(encoding="utf-8"))
        return text[-max_chars:] if max_chars > 0 and len(text) > max_chars else text

    def append_history(self, entry: str) -> None:
        text = entry.strip()
        if text:
            _append_text(self.history_file, text, trailing_blank_line=True)

    def append_history_once(self, entry: str, *, source_ref: str, kind: str) -> bool:
        return self._append_once(
            self.history_file,
            entry,
            source_ref=source_ref,
            kind=kind,
            trailing_blank_line=True,
        )

    def append_journal(
        self,
        date_str: str,
        entry: str,
        *,
        source_ref: str,
        kind: str = "journal",
    ) -> bool:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            return False
        journal_path = self.journal_dir / f"{date_str}.md"
        if not journal_path.exists():
            journal_path.write_text(f"# {date_str}\n\n", encoding="utf-8")
        return self._append_once(
            journal_path,
            entry,
            source_ref=source_ref,
            kind=kind,
            trailing_blank_line=True,
        )

    def read_pending(self) -> str:
        return self._strip_markers(self.pending_file.read_text(encoding="utf-8"))

    def append_pending(self, facts: str) -> None:
        text = facts.strip()
        if text:
            _append_text(self.pending_file, text, trailing_blank_line=False)

    def append_pending_once(self, facts: str, *, source_ref: str, kind: str) -> bool:
        return self._append_once(
            self.pending_file,
            facts,
            source_ref=source_ref,
            kind=kind,
            trailing_blank_line=False,
        )

    @property
    def snapshot_path(self) -> Path:
        return self.pending_file.with_name("PENDING.snapshot.md")

    def snapshot_pending(self) -> str:
        self._recover_pending_snapshot()
        if not self.pending_file.exists() or self.pending_file.stat().st_size == 0:
            return ""
        self.pending_file.rename(self.snapshot_path)
        self.pending_file.touch()
        return self._strip_markers(self.snapshot_path.read_text(encoding="utf-8"))

    def commit_pending_snapshot(self) -> None:
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
        if not self.pending_file.exists():
            self.pending_file.touch()

    def rollback_pending_snapshot(self) -> None:
        if not self.snapshot_path.exists():
            return
        snapshot = self.snapshot_path.read_text(encoding="utf-8")
        current = self.pending_file.read_text(encoding="utf-8") if self.pending_file.exists() else ""
        merged = snapshot.rstrip() + ("\n" + current if current.strip() else "")
        self.pending_file.write_text(merged, encoding="utf-8")
        self.snapshot_path.unlink()

    def get_memory_context(self) -> str:
        memory = self.read_long_term().strip()
        return f"## Long-term Memory\n\n{memory}" if memory else ""

    def _recover_pending_snapshot(self) -> None:
        if self.snapshot_path.exists():
            self.rollback_pending_snapshot()

    def _ensure_user(self) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, metadata, updated_at)
                    VALUES (%s, '{}'::jsonb, now())
                    ON CONFLICT (id) DO UPDATE SET updated_at = now()
                    """,
                    (self.user_id,),
                )
            conn.commit()

    def _append_once(
        self,
        target: Path,
        text: str,
        *,
        source_ref: str,
        kind: str,
        trailing_blank_line: bool,
    ) -> bool:
        content = text.strip()
        if not content:
            return False
        marker = self._marker(source_ref, kind)
        target_key = str(target.relative_to(self.memory_dir))
        with self._lock, self.db.connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO memory_markdown_writes (
                            user_id, source_ref, kind, target, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            self.user_id,
                            source_ref,
                            kind,
                            target_key,
                            datetime.now().astimezone(),
                        ),
                    )
                except IntegrityError:
                    conn.rollback()
                    return False
            _append_text(target, f"{marker}\n{content}", trailing_blank_line=trailing_blank_line)
            conn.commit()
        return True

    @staticmethod
    def _marker(source_ref: str, kind: str) -> str:
        safe_source = source_ref.replace("\n", " ").strip()
        safe_kind = kind.replace("\n", " ").strip()
        return f"{_MARKER_PREFIX}{safe_source}:{safe_kind}{_MARKER_SUFFIX}"

    @staticmethod
    def _strip_markers(text: str) -> str:
        return "\n".join(
            line
            for line in text.splitlines()
            if not (line.startswith(_MARKER_PREFIX) and line.endswith(_MARKER_SUFFIX))
        )


class MarkdownMemoryMaintenance:
    def __init__(
        self,
        *,
        store: MarkdownMemoryStore,
        provider: MemoryChatProvider,
        model: str,
        keep_count: int = 12,
        session_manager: SessionManager | None = None,
        event_bus: EventBus | None = None,
        long_term_memory: MemoryEngine | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.model = model
        self.keep_count = max(1, int(keep_count))
        self.min_new_messages = max(5, self.keep_count // 2)
        self.session_manager = session_manager
        self.long_term_memory = long_term_memory
        if event_bus is not None:
            event_bus.on(TurnCommitted, self.on_turn_committed)

    async def on_turn_committed(self, event: TurnCommitted) -> None:
        if event.extra.get("skip_post_memory"):
            return
        if self.session_manager is None:
            return
        session = self.session_manager.get_or_create(event.session_key)
        if self._should_consolidate(session):
            result = await self.consolidate(ConsolidateRequest(session=session))
            if result.trace.get("mode") != "skipped":
                self.session_manager.save(session)
        else:
            await self.refresh_recent_turns(RefreshRecentTurnsRequest(session=session))

    async def refresh_recent_turns(self, request: RefreshRecentTurnsRequest) -> None:
        existing = self.store.read_recent_context()
        recent = _format_recent_context_messages(_recent_turn_messages(request.session, self.keep_count))
        self.store.write_recent_context(_replace_recent_turns_block(existing, recent))

    async def consolidate(self, request: ConsolidateRequest) -> ConsolidateResult:
        window = _select_window(
            request.session,
            keep_count=self.keep_count,
            min_new_messages=self.min_new_messages,
            archive_all=request.archive_all,
            force=request.force,
        )
        if window is None:
            return ConsolidateResult(trace={"mode": "skipped"})
        draft = await self._prepare_draft(request.session, window, request.archive_all)
        if draft is None:
            return ConsolidateResult(trace={"mode": "skipped"})
        committed_entries = self._commit_draft(request.session, draft)
        memory_trace = await self._ingest_long_term_memory(draft, committed_entries)
        return ConsolidateResult(
            consolidated_count=len(draft.window.old_messages),
            trace={
                "mode": "markdown",
                "source_ref": draft.source_ref,
                "long_term_memory_ingest": memory_trace,
            },
        )

    def _should_consolidate(self, session: Session) -> bool:
        return (
            _select_window(
                session,
                keep_count=self.keep_count,
                min_new_messages=self.min_new_messages,
                archive_all=False,
                force=False,
            )
            is not None
        )

    async def _prepare_draft(
        self,
        session: Session,
        window: _ConsolidationWindow,
        archive_all: bool,
    ) -> _ConsolidationDraft | None:
        source_ref = _source_ref(window.old_messages)
        conversation = _format_conversation_for_consolidation(window.old_messages)
        if not source_ref or not conversation:
            return None
        prompt = _build_consolidation_prompt(
            current_memory=self.store.read_long_term(),
            recent_history=self.store.read_history(max_chars=8000),
            conversation=conversation,
        )
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": "你是记忆提取代理，只返回合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=self.model,
            max_tokens=1024,
            disable_thinking=True,
        )
        parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
        if parsed is None:
            return None
        history_entries = _normalize_history_entries(parsed.get("history_entries"))
        pending_items = _format_pending_items(parsed.get("pending_items"))
        recent_context = await self._build_recent_context_snapshot(session, window, archive_all)
        return _ConsolidationDraft(
            window=window,
            source_ref=source_ref,
            history_entries=history_entries,
            pending_items=pending_items,
            recent_context_text=recent_context,
            conversation=conversation,
            archive_all=archive_all,
        )

    async def _build_recent_context_snapshot(
        self,
        session: Session,
        window: _ConsolidationWindow,
        archive_all: bool,
    ) -> str:
        tail = _recent_turn_messages(session, self.keep_count)
        recent_turns = _format_recent_context_messages(tail)
        conversation = _format_conversation_for_recent_context(window.old_messages)
        old_recent = self.store.read_recent_context()
        compression = _extract_recent_context_compression(old_recent)
        if conversation:
            prompt = _build_recent_context_prompt(old_recent, conversation, recent_turns)
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "你是近期语境压缩代理，只返回合法 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                tools=[],
                model=self.model,
                max_tokens=512,
                disable_thinking=True,
            )
            parsed = _parse_json_object(str(getattr(response, "content", "") or ""))
            if isinstance(parsed, dict):
                compression = _normalize_recent_context_payload(parsed)
        compression_until = str(window.old_messages[-1].get("timestamp") or "")
        return _render_recent_context(
            compression=compression,
            compression_until=compression_until,
            recent_turns=recent_turns,
        )

    def _commit_draft(self, session: Session, draft: _ConsolidationDraft) -> list[str]:
        committed_entries: list[str] = []
        if draft.history_entries:
            appended_history = self.store.append_history_once(
                "\n".join(draft.history_entries),
                source_ref=draft.source_ref,
                kind="history_entry",
            )
            if appended_history:
                committed_entries.extend(draft.history_entries)
            for entry in draft.history_entries if appended_history else []:
                match = _DATE_RE.match(entry)
                if match:
                    self.store.append_journal(
                        match.group(1),
                        entry,
                        source_ref=_entry_source_ref(draft.source_ref, entry),
                    )
        if draft.pending_items:
            self.store.append_pending_once(
                draft.pending_items,
                source_ref=draft.source_ref,
                kind="pending_items",
            )
        self.store.write_recent_context(draft.recent_context_text)
        session.last_consolidated = 0 if draft.archive_all else draft.window.consolidate_up_to
        return committed_entries

    async def _ingest_long_term_memory(
        self,
        draft: _ConsolidationDraft,
        entries: list[str],
    ) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }
        if self.long_term_memory is None:
            return trace
        requests: list[MemoryWriteRequest] = [
            MemoryWriteRequest(
                summary=entry,
                memory_type="event",
                source_ref=build_entry_source_ref(draft.source_ref, entry),
                happened_at=parse_history_entry_happened_at(entry),
            )
            for entry in entries
        ]
        for line in draft.pending_items.splitlines():
            request = _pending_line_to_ingest_request(draft.source_ref, line)
            if request is not None:
                requests.append(request)
        if not requests:
            return trace
        for request in requests:
            trace["attempted"] += 1
            try:
                result = await self.long_term_memory.memorize(
                    request
                )
            except Exception as error:
                trace["failed"] += 1
                trace["errors"].append(
                    {
                        "source_ref": request.source_ref,
                        "kind": request.memory_type,
                        "error": str(error),
                    }
                )
                continue
            if result.status in {"new", "reinforced", "skipped"}:
                trace["succeeded"] += 1
            else:
                trace["failed"] += 1
                trace["errors"].append(
                    {
                        "source_ref": request.source_ref,
                        "kind": request.memory_type,
                        "status": result.status,
                    }
                )
        return trace


class MemoryOptimizerBusy(RuntimeError):
    pass


class MemoryOptimizer:
    def __init__(
        self,
        *,
        store: MarkdownMemoryStore,
        provider: MemoryChatProvider,
        model: str,
        max_tokens: int = 4096,
    ) -> None:
        self.store = store
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    async def optimize(self) -> None:
        if self._lock.locked():
            raise MemoryOptimizerBusy("memory optimizer is already running")
        async with self._lock:
            pending = self.store.snapshot_pending()
            current_memory = self.store.read_long_term().strip()
            if not pending.strip() and not current_memory:
                self.store.commit_pending_snapshot()
                return
            try:
                merged = await self._merge_memory(current_memory, pending)
                if not merged:
                    self.store.rollback_pending_snapshot()
                    return
                if current_memory:
                    self.store.backup_long_term()
                self.store.write_long_term(merged)
                if pending.strip():
                    self.store.append_history(f"[memory_optimizer] PENDING archived:\n{pending.strip()}")
                self.store.commit_pending_snapshot()
            except Exception:
                self.store.rollback_pending_snapshot()
                raise

    async def _merge_memory(self, current_memory: str, pending: str) -> str:
        prompt = _build_memory_merge_prompt(current_memory=current_memory, pending=pending)
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": "你是用户长期记忆整理器。只输出完整 MEMORY.md。"},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=self.model,
            max_tokens=self.max_tokens,
            disable_thinking=True,
        )
        return str(getattr(response, "content", "") or "").strip()


@dataclass
class MarkdownMemoryRuntime:
    store: MarkdownMemoryStore
    maintenance: MarkdownMemoryMaintenance
    optimizer: MemoryOptimizer


def build_markdown_memory_runtime(
    *,
    workspace_root: str | Path,
    provider: LLMProvider,
    model: str,
    session_manager: SessionManager | None = None,
    event_bus: EventBus | None = None,
    keep_count: int = 12,
    long_term_memory: MemoryEngine | None = None,
    user_id: int = 1,
    db: PostgresDatabase | None = None,
) -> MarkdownMemoryRuntime:
    store = MarkdownMemoryStore(workspace_root, user_id=user_id, db=db)
    maintenance = MarkdownMemoryMaintenance(
        store=store,
        provider=provider,
        model=model,
        keep_count=keep_count,
        session_manager=session_manager,
        event_bus=event_bus,
        long_term_memory=long_term_memory,
    )
    optimizer = MemoryOptimizer(store=store, provider=provider, model=model)
    return MarkdownMemoryRuntime(store=store, maintenance=maintenance, optimizer=optimizer)


def _select_window(
    session: Session,
    *,
    keep_count: int,
    min_new_messages: int,
    archive_all: bool,
    force: bool,
) -> _ConsolidationWindow | None:
    messages = list(session.messages)
    if archive_all:
        old_messages = [message for message in messages if is_real_memory_message(message)]
        return _ConsolidationWindow(old_messages=old_messages, consolidate_up_to=len(messages))
    if not force and len(messages) <= keep_count:
        return None
    consolidate_up_to = len(messages) if force else len(messages) - keep_count
    if not force and consolidate_up_to - session.last_consolidated < min_new_messages:
        return None
    old_messages = [
        message
        for message in messages[session.last_consolidated : consolidate_up_to]
        if is_real_memory_message(message)
    ]
    if not old_messages:
        return None
    return _ConsolidationWindow(old_messages=old_messages, consolidate_up_to=consolidate_up_to)


def _recent_turn_messages(session: Session, keep_count: int) -> list[dict[str, Any]]:
    recent_count = max(1, keep_count // 2)
    return list(session.messages[-recent_count:])


def _format_recent_context_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        if not is_real_memory_message(message):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if message.get("role") == "assistant":
            lines.append(f"[a-preview] {content[:60]}")
        elif message.get("role") == "user":
            lines.append(f"[user] {content}")
    return "\n".join(lines)


def _replace_recent_turns_block(existing: str, recent_turns: str) -> str:
    block = "\n".join(
        [
            "## Recent Turns",
            "<!-- a-preview = assistant reply preview only -->",
            recent_turns.strip() or "- none",
        ]
    ).rstrip()
    marker = "\n## Recent Turns\n"
    text = existing.strip()
    if marker in text:
        prefix, _ = text.split(marker, 1)
        return prefix.rstrip() + "\n\n" + block + "\n"
    if text:
        return text + "\n\n" + block + "\n"
    return _render_recent_context(
        compression=None,
        compression_until="none",
        recent_turns=recent_turns,
    )


def _format_conversation_for_consolidation(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        if not is_real_memory_message(message):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        role = str(message.get("role") or "").upper()
        ts = str(message.get("timestamp") or "")[:16] or "?"
        lines.append(f"[{ts}] {role}: {content}")
    return "\n".join(lines)


def _format_conversation_for_recent_context(messages: list[dict[str, Any]]) -> str:
    return _format_conversation_for_consolidation(messages)


def _source_ref(messages: list[dict[str, Any]]) -> str:
    ids = [str(message.get("id")) for message in messages if message.get("id")]
    return json.dumps(ids, ensure_ascii=False) if ids else ""


def _entry_source_ref(source_ref: str, entry: str) -> str:
    return build_entry_source_ref(source_ref, entry)


def _pending_line_to_ingest_request(
    source_ref: str,
    line: str,
) -> MemoryWriteRequest | None:
    match = re.match(r"^- \[(?P<tag>[a-z_]+)\] (?P<content>.+)$", line.strip())
    if not match:
        return None
    tag = match.group("tag")
    content = match.group("content").strip()
    if not content:
        return None
    kind_by_tag = {
        "identity": "profile",
        "preference": "preference",
        "key_info": "fact",
        "health_long_term": "fact",
        "requested_memory": "fact",
        "correction": "fact",
        "agent_context": "constraint",
    }
    kind = kind_by_tag.get(tag)
    if kind is None:
        return None
    extra = {"memory_tag": tag}
    if tag == "correction":
        extra["lifecycle"] = "correction"
    return MemoryWriteRequest(
        summary=content,
        memory_type=kind,
        source_ref=build_entry_source_ref(source_ref, line),
        extra=extra,
    )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.S)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_history_entries(raw: Any) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    candidates = raw if isinstance(raw, list) else [raw] if raw is not None else []
    for item in candidates:
        if isinstance(item, dict):
            text = str(item.get("summary") or "").strip()
        else:
            text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            entries.append(text)
    return entries


def _format_pending_items(raw: Any) -> str:
    if not isinstance(raw, list):
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if tag not in _ALLOWED_PENDING_TAGS or not content:
            continue
        line = f"- [{tag}] {content}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def _render_recent_context(
    *,
    compression: dict[str, list[str]] | None,
    compression_until: str,
    recent_turns: str,
) -> str:
    compression = compression or {}
    sections = [
        ("最近持续关注", compression.get("active_topics") or []),
        ("最近明确偏好", compression.get("user_preferences") or []),
        ("最近待延续话题", compression.get("follow_ups") or []),
        ("最近避免事项", compression.get("avoidances") or []),
    ]
    lines = ["# Recent Context", "", "## Compression", f"until: {compression_until or 'none'}"]
    rendered = False
    for title, items in sections:
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if cleaned:
            rendered = True
            lines.append(f"- {title}：{'；'.join(cleaned[:3])}")
    if not rendered:
        lines.append("- none")
    lines.extend(["", "## Ongoing Threads"])
    ongoing = [str(item).strip() for item in (compression.get("ongoing_threads") or []) if str(item).strip()]
    lines.extend([f"- {item}" for item in ongoing[:3]] or ["- none"])
    lines.extend(["", "## Recent Turns", "<!-- a-preview = assistant reply preview only -->"])
    lines.append(recent_turns.strip() or "- none")
    return "\n".join(lines).rstrip() + "\n"


def _extract_recent_context_compression(text: str) -> dict[str, list[str]] | None:
    if not text.strip():
        return None
    result: dict[str, list[str]] = {
        "active_topics": [],
        "user_preferences": [],
        "follow_ups": [],
        "avoidances": [],
        "ongoing_threads": [],
    }
    title_map = {
        "最近持续关注": "active_topics",
        "最近明确偏好": "user_preferences",
        "最近待延续话题": "follow_ups",
        "最近避免事项": "avoidances",
    }
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or "：" not in stripped:
            continue
        title, values = stripped[2:].split("：", 1)
        key = title_map.get(title)
        if key:
            result[key] = [item.strip() for item in values.split("；") if item.strip()][:3]
    ongoing_match = re.search(r"## Ongoing Threads\n(?P<body>.*?)(?:\n## Recent Turns\n|\Z)", text, flags=re.S)
    if ongoing_match:
        result["ongoing_threads"] = [
            line.strip()[2:]
            for line in ongoing_match.group("body").splitlines()
            if line.strip().startswith("- ") and line.strip() != "- none"
        ][:3]
    return result


def _normalize_recent_context_payload(payload: dict[str, Any]) -> dict[str, list[str]]:
    return {
        key: [str(item).strip() for item in (payload.get(key) or []) if str(item).strip()][:3]
        for key in (
            "active_topics",
            "user_preferences",
            "follow_ups",
            "avoidances",
            "ongoing_threads",
        )
    }


def _build_consolidation_prompt(
    *,
    current_memory: str,
    recent_history: str,
    conversation: str,
) -> str:
    return f"""从下面待处理对话中提取两类记忆材料，返回 JSON。

要求：
- history_entries 只记录 USER 明确表达的行动、经历、计划和状态。
- pending_items 只记录跨对话仍有长期价值的用户事实、偏好、key 信息、长期健康事实、用户明确要求长期记住的内容、更正、助手操作上下文。
- 不要把 ASSISTANT 的建议当作用户事实。
- 不要写短期状态、工具流程、执行规则、普通寒暄。
- transcript / 截图 / 转贴聊天中 speaker 身份不明确时，只写一条高层 history_entry。

返回格式：
{{
  "history_entries": [{{"summary": "[YYYY-MM-DD HH:MM] ..."}}],
  "pending_items": [{{"tag": "identity|preference|key_info|health_long_term|requested_memory|correction|agent_context", "content": "..."}}]
}}

当前用户档案：
{current_memory or "（空）"}

最近历史摘要：
{recent_history or "（空）"}

待处理对话：
{conversation}
"""


def _build_recent_context_prompt(old_recent: str, conversation: str, recent_turns: str) -> str:
    return f"""为后续对话抽取近期语境，只返回 JSON。

规则：
- 只依据 USER 内容。
- active_topics 写最近持续关注的话题。
- user_preferences 只写明确偏好或禁忌。
- follow_ups 写适合续接的话题。
- avoidances 只写明确不要/避免/不想。
- ongoing_threads 只写对用户生活、工作、健康、情绪有持续影响的线索。

返回字段：
active_topics, user_preferences, follow_ups, avoidances, ongoing_threads

上一版 recent context：
{old_recent or "（空）"}

较早窗口：
{conversation or "（空）"}

最新 recent turns：
{recent_turns or "（空）"}
"""


def _build_memory_merge_prompt(*, current_memory: str, pending: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""今日日期：{today}

你的任务是将「现有用户档案」重新整理为完整、精炼的 MEMORY.md，同时合并「待合并事实」。

保留标准：6 个月后如果没有这条信息，助手是否会在回复中出现方向性失误。

必须保留：
- 用户稳定身份事实
- 用户长期偏好和禁忌
- 用户明确要求长期记住的关键内容
- 助手操作用户环境所需的长期配置

必须删除：
- 短期状态、瞬时情绪、时效性数字
- agent 执行规则、SOP、工具调用流程
- 普通对话总结

输出格式：
- 标题 `# 用户长期记忆`
- 使用 `## 用户事实`、`## 用户偏好`、`## 用户明确要求长期记住的关键内容`、`## 助手操作上下文`
- 直接输出完整 MEMORY.md，不要 JSON，不要解释

现有用户档案：
{current_memory or "（空）"}

待合并事实：
{pending or "（无新内容）"}
"""


def _append_text(path: Path, text: str, *, trailing_blank_line: bool) -> None:
    suffix = "\n\n" if trailing_blank_line else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.rstrip() + suffix)
