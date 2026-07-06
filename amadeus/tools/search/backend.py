from __future__ import annotations

import re
from dataclasses import dataclass

from amadeus.tools.search.document import ToolDocument


@dataclass(frozen=True)
class SearchResult:
    name: str
    summary: str
    why_matched: list[str]
    risk: str
    always_on: bool


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= code <= 0x4DBF  # CJK Extension A
        or 0x3040 <= code <= 0x30FF  # Hiragana / Katakana
    )


def _default_normalize(text: str) -> list[str]:
    """lowercase + 空格切词 + CJK 边界切 + bigram。

    对 CJK 段做相邻两字 bigram；对 ASCII 段按空白切词。
    """
    text = text.lower().strip()
    if not text:
        return []
    tokens: list[str] = []
    buf: list[str] = []
    for ch in text:
        if _is_cjk(ch):
            buf.append(ch)
        else:
            if buf:
                tokens.extend(_cjk_bigrams(buf))
                buf = []
            if ch.isalnum():
                tokens.append(ch)
            elif tokens and tokens[-1] != " ":
                tokens.append(" ")
    if buf:
        tokens.extend(_cjk_bigrams(buf))
    # 把单词字符拼成 word，过滤分隔
    result: list[str] = []
    word = ""
    for tok in tokens:
        if tok == " ":
            if word:
                result.append(word)
                word = ""
            continue
        if len(tok) == 1 and tok.isalnum():
            word += tok
        else:
            if word:
                result.append(word)
                word = ""
            result.append(tok)
    if word:
        result.append(word)
    return [t for t in result if t]


def _cjk_bigrams(chars: list[str]) -> list[str]:
    if len(chars) <= 1:
        return chars
    grams: list[str] = []
    for i in range(len(chars) - 1):
        grams.append(chars[i] + chars[i + 1])
    # 也保留单字作为弱信号
    grams.extend(chars)
    return grams


def _split_name_parts(name: str) -> list[str]:
    """按下划线/短横线切工具名，用于 name parts 评分。"""
    parts = re.split(r"[_\-]+", name)
    return [p.lower() for p in parts if p]


class KeywordSearchBackend:
    """关键词打分检索：CJK bigram 加权 + why_matched 解释与打分解耦。"""

    def __init__(self) -> None:
        self._documents: dict[str, ToolDocument] = {}

    def add(self, doc: ToolDocument) -> None:
        self._documents[doc.name] = doc

    def remove(self, name: str) -> None:
        self._documents.pop(name, None)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        allowed_risk: set[str] | None = None,
        excluded_names: set[str] | None = None,
    ) -> list[SearchResult]:
        if not query:
            return []
        excluded = excluded_names or set()
        q_norm = query.lower().strip()

        # 精确名匹配 fast path
        if q_norm in self._documents and q_norm not in excluded:
            doc = self._documents[q_norm]
            if allowed_risk is None or doc.risk in allowed_risk:
                return [
                    SearchResult(
                        name=doc.name,
                        summary=doc.description[:120],
                        why_matched=["名称:精确匹配"],
                        risk=doc.risk,
                        always_on=doc.always_on,
                    )
                ]

        # select: 前缀走精确匹配（不在此处理，由调用方处理）；普通 query 走打分
        q_tokens = _default_normalize(query)
        scored: list[tuple[float, ToolDocument, list[str]]] = []
        for doc in self._documents.values():
            if doc.name in excluded:
                continue
            if allowed_risk is not None and doc.risk not in allowed_risk:
                continue
            score, why = self._score(doc, q_norm, q_tokens)
            if score > 0:
                scored.append((score, doc, why))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [
            SearchResult(
                name=doc.name,
                summary=doc.description[:120],
                why_matched=why,
                risk=doc.risk,
                always_on=doc.always_on,
            )
            for score, doc, why in scored[:top_k]
        ]

    def _score(
        self, doc: ToolDocument, q_norm: str, q_tokens: list[str]
    ) -> tuple[float, list[str]]:
        score = 0.0
        why: list[str] = []

        # name parts 加权
        name_parts = _split_name_parts(doc.name)
        for part in name_parts:
            if part == q_norm:
                score += 10
                why.append("名称:精确匹配")
                break
            if part and (part in q_norm or q_norm in part):
                score += 5
                why.append(f"名称:部分匹配({part})")
                break
        else:
            # 全名 substring 兜底
            if q_norm and q_norm in doc.name.lower():
                score += 3
                why.append("名称:包含")

        # search_hint
        if doc.search_hint:
            hint_lower = doc.search_hint.lower()
            for tok in q_tokens:
                if tok and tok in hint_lower:
                    score += 4
                    why.append(f"搜索提示:{tok}")
                    break

        # description
        desc_lower = doc.description.lower()
        for tok in q_tokens:
            if tok and len(tok) > 1 and tok in desc_lower:
                score += 2
                why.append(f"描述:{tok}")
                break

        # MCP 工具本身不加分；只有已有匹配分时加小幅权重让 MCP 工具在同等匹配下排前
        if score > 0 and doc.source_type == "mcp":
            score += 2

        return score, why