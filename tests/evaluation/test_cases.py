from __future__ import annotations

from pathlib import Path

import pytest
from amadeus.evaluation.cases import (
    load_memory_quality_cases,
    load_memory_recall_cases,
)


def test_load_memory_recall_cases_parses_repo_shape(tmp_path: Path):
    case_file = tmp_path / "cases.yaml"
    case_file.write_text(
        """
cases:
  - id: recall-1
    mode: recall_tool
    title: recall title
    seed_session_messages:
      - role: user
        content: hello
    seed_long_term_memories:
      - summary: remember hello
        memory_type: fact
        source_message_indexes: [0]
        embedding_mode: null
    input:
      recall_query: hello
    expect:
      source_ref_required: true
      candidate_counts_min:
        lexical: 1
      lane_status_equals:
        lexical: ok
      record_lane_expectations:
        - summary_contains: remember hello
          lanes_contains: [lexical]
          lanes_excludes: [vector]
      fetched_messages_contains: [hello]
      answer_keywords_any: [hello]
      judge_rubric: mention hello
""".strip(),
        encoding="utf-8",
    )

    cases = load_memory_recall_cases(case_file)

    assert len(cases) == 1
    assert cases[0].id == "recall-1"
    assert cases[0].mode == "recall_tool"
    assert cases[0].seed_long_term_memories[0].source_message_indexes == (0,)
    assert cases[0].seed_long_term_memories[0].embedding_mode == "null"
    assert cases[0].input_payload["recall_query"] == "hello"
    assert cases[0].expect.source_ref_required is True
    assert cases[0].expect.candidate_counts_min == {"lexical": 1}
    assert cases[0].expect.lane_status_equals == {"lexical": "ok"}
    assert cases[0].expect.record_lane_expectations[0].summary_contains == (
        "remember hello"
    )
    assert cases[0].expect.record_lane_expectations[0].lanes_contains == ("lexical",)
    assert cases[0].expect.record_lane_expectations[0].lanes_excludes == ("vector",)


def test_canonical_memory_recall_cases_include_strict_lexical_only_fixture():
    case_file = Path(__file__).parent / "cases" / "memory_recall_v1.yaml"

    cases = load_memory_recall_cases(case_file)

    lexical_case = next(
        case for case in cases if case.id == "recall_tool_returns_source_refs"
    )
    assert lexical_case.seed_long_term_memories[0].embedding_mode == "null"
    expectation = lexical_case.expect.record_lane_expectations[0]
    assert expectation.lanes_contains == ("lexical",)
    assert expectation.lanes_excludes == ("vector",)


def test_load_memory_recall_cases_rejects_missing_required_fields(tmp_path: Path):
    case_file = tmp_path / "cases.yaml"
    case_file.write_text(
        """
cases:
  - id: bad-case
    title: missing mode
    seed_session_messages: []
    seed_long_term_memories: []
    input:
      user_message: hello
    expect:
      judge_rubric: say hello
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bad-case"):
        load_memory_recall_cases(case_file)


def test_load_memory_quality_cases_parses_repo_shape(tmp_path: Path):
    case_file = tmp_path / "memory_quality.yaml"
    case_file.write_text(
        """
cases:
  - id: quality-1
    mode: write_then_recall
    title: write and recall
    seed_session_messages:
      - role: user
        content: 旧消息
    seed_long_term_memories:
      - summary: 用户以前偏好英文
        memory_type: preference
        source_ref: '["session:1:1:10"]#h:old'
    turn_messages:
      - role: user
        content: 以后默认用中文回复
        timestamp: "2026-07-02T10:00:00+08:00"
    input:
      recall_query: 中文回复
    expect:
      write_count_min: 1
      written_summaries_contains: [中文]
      active_summaries_contains: [中文]
      memory_types_contains: [preference]
      source_ref_required: true
      judge_rubric: memory should capture the Chinese preference
""".strip(),
        encoding="utf-8",
    )

    cases = load_memory_quality_cases(case_file)

    assert len(cases) == 1
    assert cases[0].id == "quality-1"
    assert cases[0].mode == "write_then_recall"
    assert cases[0].turn_messages[0].content == "以后默认用中文回复"
    assert cases[0].input_payload["recall_query"] == "中文回复"
    assert cases[0].expect.write_count_min == 1
    assert cases[0].expect.memory_types_contains == ("preference",)


def test_load_memory_quality_cases_rejects_missing_turn_messages(tmp_path: Path):
    case_file = tmp_path / "memory_quality.yaml"
    case_file.write_text(
        """
cases:
  - id: bad-quality
    mode: post_response_write
    title: missing turn messages
    seed_session_messages: []
    seed_long_term_memories: []
    input: {}
    expect:
      write_count_max: 0
      judge_rubric: should not write anything
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bad-quality"):
        load_memory_quality_cases(case_file)
