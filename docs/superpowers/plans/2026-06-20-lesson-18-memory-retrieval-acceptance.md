# Lesson 18 Memory / Retrieval Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that passive retrieval, recall, search, fetch, evidence/source-ref resolution, correction, and forgetting form one coherent Amadeus runtime chain, then fix only reproducible contract gaps.

**Architecture:** Acceptance is driven by integration tests at public tool/runtime boundaries. Production changes are limited to tool descriptions, recall output metadata, and behavior rules when tests prove those contracts diverge from Akashic. Retrieval ranking and storage architecture remain unchanged.

**Tech Stack:** Python 3.11, pytest, existing Amadeus runtime/tool registry, HTML teaching artifact, ruff, mypy.

---

## File map

- Create `tests/test_memory_retrieval_acceptance.py`: cross-tool contract tests and eval seeds.
- Modify `amadeus/tools/recall_memory.py`: preserve complete evidence and citation metadata if acceptance tests fail.
- Modify `amadeus/tools/defaults.py`: state search/fetch evidence boundaries in schemas/descriptions.
- Modify `amadeus/prompts/__init__.py`: add history retrieval and correction protocol if prompt audit fails.
- Create `lessons/0013-lesson-18-memory-retrieval-acceptance-part-1.html`: Akashic source lesson, actual validation evidence and gap audit.
- Do not create a Lesson 18 learning record until the user retells the joint chain.

### Task 1: Capture Akashic source contracts

**Files:**
- Read: `../akashic-agent/agent/tools/recall_memory.py`
- Read: `../akashic-agent/agent/tools/message_lookup.py`
- Read: `../akashic-agent/agent/tools/forget_memory.py`
- Read: `../akashic-agent/prompts/agent.py`
- Read: corresponding Akashic tests named in the Lesson 18 design

- [ ] **Step 1: Record the source-to-test map**

For each tool, record input ID type, output evidence shape, which result is candidate versus original evidence, and the test that locks the behavior. The acceptance matrix must distinguish memory IDs from message IDs.

- [ ] **Step 2: Confirm which contracts are runtime-enforced versus prompt-enforced**

Expected distinction:

```text
runtime-enforced: source_ref parsing, message fetching, soft-delete by memory ID
prompt-enforced: recall before fetch, fetch before factual answer/forget, citation marker
```

### Task 2: Add joint recall/search/fetch acceptance tests

**Files:**
- Create: `tests/test_memory_retrieval_acceptance.py`

- [ ] **Step 1: Write the recall → evidence → fetch test**

Use a real `SessionManager`, `VectorMemoryStore`, `VectorMemoryEngine`, `RecallMemoryTool`, and `FetchMessagesTool`. Persist source messages, ingest one memory with a hashed source ref, recall it, pass the returned evidence directly into fetch, and assert the original messages return in source order.

- [ ] **Step 2: Write the search → source_ref → fetch test**

Search for a literal term, pass the returned `source_ref` into fetch, and assert the full original message is returned rather than only the preview.

- [ ] **Step 3: Write the memory-ID versus message-ID correction test**

Fetch by the recalled evidence first, then call `forget_memory(ids=[memory_id])`. Assert the vector item becomes superseded while the source session message remains fetchable. Also assert passing a message ID to forget reports it as missing.

- [ ] **Step 4: Run integration tests**

Run: `uv run --extra dev pytest tests/test_memory_retrieval_acceptance.py -v`

Expected: data-path tests pass if the existing runtime contracts compose correctly.

### Task 3: Add prompt/schema acceptance tests

**Files:**
- Modify: `tests/test_memory_retrieval_acceptance.py`

- [ ] **Step 1: Write tests for candidate/evidence boundaries**

Assert:

```python
assert "fetch_messages" in RecallMemoryTool(memory_engine=None).description
assert "最终证据" in FetchMessagesTool(store=store).description
assert "fetch_messages" in SearchMessagesTool(store=store).description
```

- [ ] **Step 2: Write tests for correction ordering**

Build the behavior-rules prompt and assert it requires recall/search location, fetch of original messages, then forget by memory ID. Assert it explicitly forbids using a message ID as a memory ID.

- [ ] **Step 3: Write citation/evidence shape tests**

Assert recall output includes complete evidence entries with `source_ref`, plus `citation_required`, `citation_format`, `cited_item_ids`, and a rule that only actually used IDs are cited.

- [ ] **Step 4: Run and capture the expected red result**

Run: `uv run --extra dev pytest tests/test_memory_retrieval_acceptance.py -v`

Expected before the minimal fix: description, prompt protocol, evidence `source_ref`, and citation fields fail; data-path tests remain green.

### Task 4: Apply the minimal contract fix

**Files:**
- Modify: `amadeus/tools/recall_memory.py`
- Modify: `amadeus/tools/defaults.py`
- Modify: `amadeus/prompts/__init__.py`
- Test: `tests/test_memory_retrieval_acceptance.py`

- [ ] **Step 1: Strengthen tool descriptions**

State that recall/search results are candidate summaries/previews and that `fetch_messages` is the original-message evidence tool. Keep the descriptions operational and name the exact handoff field.

- [ ] **Step 2: Preserve complete evidence and citation metadata**

Include `source_ref` in each recall evidence object. Add:

```python
"citation_required": True,
"citation_format": "§cited:[id1,id2,...]§",
"cited_item_ids": [item["id"] for item in items],
"citation_rule": "Only cite memory IDs actually used in the final answer.",
```

This aligns the tool output contract; enforcement remains a documented future citation-plugin gap.

- [ ] **Step 3: Add behavior-rule protocols**

Add concise sections for history retrieval and correction:

```text
recall_memory -> fetch_messages for factual use
recall insufficient -> search_messages -> fetch_messages
correction -> locate memory ID -> fetch original -> forget memory ID
never pass message IDs to forget_memory
```

- [ ] **Step 4: Re-run acceptance tests**

Run: `uv run --extra dev pytest tests/test_memory_retrieval_acceptance.py -v`

Expected: all acceptance tests pass.

### Task 5: Run stage regression and collect evidence

**Files:**
- Test: existing memory/runtime suites

- [ ] **Step 1: Run focused memory tests**

Run:

```powershell
uv run --extra dev pytest tests/test_runtime_vector_memory.py tests/test_vector_memory.py tests/test_readonly_tools.py tests/test_forget_memory_tool.py tests/test_memory_retrieval_acceptance.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full quality gates**

Run:

```powershell
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy
```

Expected: all tests pass; ruff and mypy report no errors.

### Task 6: Create the formal Part 1 lesson

**Files:**
- Create: `lessons/0013-lesson-18-memory-retrieval-acceptance-part-1.html`

- [ ] **Step 1: Write the Akashic source lesson**

Include the source/test map, candidate-versus-evidence hierarchy, memory-ID/message-ID distinction, and prompt-enforced versus runtime-enforced boundaries.

- [ ] **Step 2: Write the Amadeus acceptance evidence**

Include exact commands, initial red failures, minimal fixes, final results, and the real joint data flow. Do not claim the citation marker is runtime-enforced.

- [ ] **Step 3: Add gap audit and eval seeds**

Record:

- citation output contract aligned; citation plugin enforcement remains a gap;
- database-level candidate retrieval remains a performance gap, not a correctness failure at current scale;
- isolated Akashic QueryRewriter/Sufficiency/HyDE classes remain out of the production-alignment scope;
- unified retrieval eval harness lands in Lesson 39.

- [ ] **Step 4: Add retelling questions**

Require the user to explain the joint chain, evidence hierarchy, deletion boundary, prompt/runtime enforcement split, and one eval seed before creating a Lesson 18 learning record.

## Plan self-review

- The plan starts with observable acceptance tests rather than speculative refactoring.
- Every production change is tied to an expected red assertion.
- Citation metadata is not misrepresented as runtime enforcement.
- No new core dependency, BM25, reranker, or isolated Akashic experimental module is introduced.
