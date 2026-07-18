import { decodeTurnEvent } from "./events";
import { initialTurnStream, reduceTurnEvent } from "./reducer";

function event(seq: number, type: string, data: Record<string, unknown>) {
  return decodeTurnEvent({
    seq,
    type,
    turn_id: "turn-1",
    occurred_at: "2026-07-19T00:00:00Z",
    data,
  });
}

describe("turn stream reducer", () => {
  it("replays text, tool lifecycle and later text in source order", () => {
    let state = initialTurnStream("turn-1", 9);
    state = reduceTurnEvent(state, event(1, "content_snapshot", { content: "我先查一下。", version: 1 }));
    state = reduceTurnEvent(state, event(2, "tool_activity", { activity_id: "call-1", tool_name: "recall_memory", state: "started" }));
    state = reduceTurnEvent(state, event(3, "tool_activity", { activity_id: "call-1", tool_name: "recall_memory", state: "completed" }));
    state = reduceTurnEvent(state, event(4, "content_snapshot", { content: "我先查一下。最终回答", version: 2 }));

    expect(state.parts).toEqual([
      { kind: "text", id: "text:1", content: "我先查一下。" },
      { kind: "tool", id: "tool:call-1", activityId: "call-1", toolName: "recall_memory", state: "completed", collapsed: true },
      { kind: "text", id: "text:4", content: "最终回答" },
    ]);
  });

  it("ignores duplicate sequences instead of duplicating text", () => {
    const first = event(1, "content_snapshot", { content: "A", version: 1 });
    const state = reduceTurnEvent(initialTurnStream("turn-1", 9), first);
    expect(reduceTurnEvent(state, first)).toBe(state);
  });

  it("closes with the safe terminal failure and preserves partial text", () => {
    let state = reduceTurnEvent(
      initialTurnStream("turn-1", 9),
      event(1, "content_snapshot", { content: "部分", version: 1 }),
    );
    state = reduceTurnEvent(
      state,
      event(2, "turn_terminal", {
        status: "failed",
        error: { error_code: "runtime_error", message: "处理失败，请重试", retryable: true },
      }),
    );
    expect(state.snapshot).toBe("部分");
    expect(state.status).toBe("failed");
    expect(state.error?.code).toBe("runtime_error");
    expect(state.connection).toBe("closed");
  });
});
