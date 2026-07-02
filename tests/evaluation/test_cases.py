from __future__ import annotations

from pathlib import Path

import pytest

from amadeus.evaluation.cases import load_memory_recall_cases


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
    input:
      recall_query: hello
    expect:
      source_ref_required: true
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
    assert cases[0].input_payload["recall_query"] == "hello"
    assert cases[0].expect.source_ref_required is True


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
