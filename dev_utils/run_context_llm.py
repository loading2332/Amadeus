import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amadeus.context import ContextBuilder, ContextRenderResult, RuntimeContext
from amadeus.workspace import initialize_workspace
from dev_utils.openai_provider import (
    OpenAICompatibleProvider,
    load_openai_compatible_config,
)


def parse_key_value_items(items: list[str] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"expected non-empty KEY in {item!r}")
        values[key] = value.strip()
    return values


def build_runtime_context(
    workspace_root: Path,
    user_message: str,
    retrieved_memory: str | None = None,
    recent_context: str | None = None,
    active_skills: list[str] | None = None,
    runtime_metadata: dict[str, str] | None = None,
) -> RuntimeContext:
    return RuntimeContext(
        workspace_root=workspace_root,
        history=[],
        current_user_message=user_message,
        retrieved_memory=retrieved_memory,
        recent_context_override=recent_context,
        active_skills=active_skills or [],
        runtime_metadata=runtime_metadata or {},
    )


def render_context_messages(context: RuntimeContext) -> ContextRenderResult:
    return ContextBuilder().render(context)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Amadeus context and send it to an OpenAI-compatible API."
    )
    parser.add_argument("message", help="Current user message to send through Amadeus.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path("."),
        help="Workspace root used by Amadeus memory prompt blocks.",
    )
    parser.add_argument("--retrieved-memory", default=None)
    parser.add_argument("--recent-context", default=None)
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Runtime metadata item in KEY=VALUE format. Can be repeated.",
    )
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument(
        "--show-messages",
        action="store_true",
        help="Print rendered messages before calling the LLM.",
    )
    args = parser.parse_args()

    workspace_root = args.workspace_root.resolve()
    initialize_workspace(workspace_root)
    context = build_runtime_context(
        workspace_root=workspace_root,
        user_message=args.message,
        retrieved_memory=args.retrieved_memory,
        recent_context=args.recent_context,
        active_skills=args.skill,
        runtime_metadata=parse_key_value_items(args.metadata),
    )
    rendered = render_context_messages(context)

    if args.show_messages:
        _print_rendered_messages(rendered)

    provider = OpenAICompatibleProvider(load_openai_compatible_config())
    result = provider.chat(
        rendered.messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    print("\n=== Assistant Output ===")
    print(result.content)
    if result.usage:
        print(f"\nusage: {dict(result.usage)}")


def _print_rendered_messages(rendered: ContextRenderResult) -> None:
    print("=== Rendered Messages ===")
    for index, message in enumerate(rendered.messages, start=1):
        print(f"\n[{index}] role={message['role']}")
        print(message["content"])

    print("\n=== Prompt Breakdown ===")
    for entry in [*rendered.system_prompt.breakdown, *rendered.context_frame.breakdown]:
        status = "rendered" if entry.rendered else f"empty: {entry.empty_reason}"
        destination = entry.destination or "unknown"
        print(
            f"- {entry.label} -> {destination}: {status}, "
            f"{entry.char_count} chars, ~{entry.estimated_tokens} tokens"
        )


if __name__ == "__main__":
    main()
