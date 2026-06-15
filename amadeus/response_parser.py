from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ResponseMetadata:
    raw_text: str


@dataclass(frozen=True)
class ParsedResponse:
    clean_text: str
    metadata: ResponseMetadata


_PAREN_LINE_RE = re.compile(r"^\s*[\(（][^()（）\n]{1,80}[\)）]\s*$")
_PAREN_RE = re.compile(r"[\(（]([^()（）\n]{1,80})[\)）]\s*")
_STAGE_HINT_RE = re.compile(
    r"(愣|脸红|耳尖|小声|语气|表情|动作|移开|低头|抬头|皱眉|笑|叹|沉默|停顿|看着|内心|心理)"
)


def parse_response(
    raw_text: str,
    *,
    tool_chain: list[dict[str, object]],
) -> ParsedResponse:
    return ParsedResponse(
        clean_text=_strip_stage_directions(raw_text),
        metadata=ResponseMetadata(raw_text=raw_text),
    )


def _strip_stage_directions(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skipping_leading = True
    for line in lines:
        if _is_stage_direction_line(line):
            continue
        if skipping_leading and not line.strip():
            continue
        skipping_leading = False
        kept.append(line)
    return _strip_inline_stage_directions("\n".join(kept)).strip()


def _is_stage_direction_line(line: str) -> bool:
    if not _PAREN_LINE_RE.match(line):
        return False
    inner = line.strip()[1:-1].strip()
    return bool(_STAGE_HINT_RE.search(inner))


def _strip_inline_stage_directions(text: str) -> str:
    def replace_stage_direction(match: re.Match[str]) -> str:
        if _STAGE_HINT_RE.search(match.group(1)):
            return ""
        return match.group(0)

    return _PAREN_RE.sub(replace_stage_direction, text)
