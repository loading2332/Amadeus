import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Turn } from "../api/contracts";
import { useLiveTurnStore } from "../streaming/store";
import { TurnItem } from "./TurnItem";

vi.mock("../api/queries", () => ({
  useRetryTurnMutation: () => ({ isPending: false, mutate: vi.fn() }),
}));

const baseTurn: Turn = {
  turnId: "turn-1",
  userId: 1,
  sessionId: 1,
  content: "你好",
  status: "pending",
  answer: null,
  partialAnswer: "",
  streamVersion: 0,
  retryOfTurnId: null,
  error: null,
  metadata: {},
  createdAt: null,
  updatedAt: null,
  startedAt: null,
  finishedAt: null,
};

describe("TurnItem", () => {
  beforeEach(() => useLiveTurnStore.getState().reset());

  it("shows progress only while the turn is active", () => {
    const { rerender } = render(<TurnItem turn={baseTurn} />);
    expect(screen.getByText("等待处理")).toBeInTheDocument();

    rerender(<TurnItem turn={{ ...baseTurn, status: "processing" }} />);
    expect(screen.getByText("正在回答")).toBeInTheDocument();
  });

  it("does not show a progress spinner after cancellation", () => {
    render(<TurnItem turn={{ ...baseTurn, status: "cancelled" }} />);

    expect(screen.queryByText("正在回答")).not.toBeInTheDocument();
    expect(screen.queryByText("等待处理")).not.toBeInTheDocument();
    expect(screen.getByText(/已停止生成/)).toBeInTheDocument();
  });

  it("does not describe a failed turn as still answering", () => {
    render(<TurnItem turn={{
      ...baseTurn,
      status: "failed",
      error: { code: "fixture_failed", message: "回答失败，已保留部分内容。", retryable: true },
    }} />);

    expect(screen.queryByText("正在回答")).not.toBeInTheDocument();
    expect(screen.getByText("回答失败，已保留部分内容。")).toBeInTheDocument();
  });

  it("shows a pulsing cursor while streamed text is arriving", async () => {
    act(() => {
      const store = useLiveTurnStore.getState();
      store.ensureTurn("turn-1", 1);
      store.applyEvent({
        type: "turn_status",
        seq: 1,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:00Z",
        status: "processing",
      });
      store.applyEvent({
        type: "content_snapshot",
        seq: 2,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:01Z",
        content: "正在生成的回答",
        version: 1,
      });
    });

    render(<TurnItem turn={{ ...baseTurn, status: "processing" }} />);
    // markdown 为 lazy chunk,全量跑并行负载下首个加载可能超过默认 1s。
    expect(await screen.findByTestId("streaming-cursor", undefined, { timeout: 5000 })).toBeInTheDocument();
  });

  it("hides the cursor once the turn reaches a terminal state", async () => {
    act(() => {
      const store = useLiveTurnStore.getState();
      store.ensureTurn("turn-1", 1);
      store.applyEvent({
        type: "content_snapshot",
        seq: 1,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:00Z",
        content: "完整回答",
        version: 1,
      });
      store.applyEvent({
        type: "turn_terminal",
        seq: 2,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:01Z",
        status: "done",
        error: null,
      });
    });

    render(<TurnItem turn={{ ...baseTurn, status: "done", answer: "完整回答" }} />);
    // 等 markdown lazy chunk 渲染完成后再断言光标不存在,避免空转通过。
    expect(await screen.findByText("完整回答", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByTestId("streaming-cursor")).not.toBeInTheDocument();
  });

  it("copies the whole answer as raw markdown once the turn is done", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const answer = "# 结论\n\n第一段。\n\n```py\nprint(1)\n```";

    render(<TurnItem turn={{ ...baseTurn, status: "done", answer }} />);
    await user.click(screen.getByRole("button", { name: "复制全文" }));

    expect(writeText).toHaveBeenCalledWith(answer);
    expect(await screen.findByText("回答已复制")).toBeInTheDocument();
  });

  it("hides the copy-answer button while the turn is streaming", () => {
    act(() => {
      const store = useLiveTurnStore.getState();
      store.ensureTurn("turn-1", 1);
      store.applyEvent({
        type: "turn_status",
        seq: 1,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:00Z",
        status: "processing",
      });
      store.applyEvent({
        type: "content_snapshot",
        seq: 2,
        turnId: "turn-1",
        occurredAt: "2026-07-27T00:00:01Z",
        content: "生成中的内容",
        version: 1,
      });
    });

    render(<TurnItem turn={{ ...baseTurn, status: "processing" }} />);
    expect(screen.queryByRole("button", { name: "复制全文" })).not.toBeInTheDocument();
  });

  it("does not offer copying when the finished turn has no answer", () => {
    render(<TurnItem turn={{ ...baseTurn, status: "done", answer: "" }} />);
    expect(screen.queryByRole("button", { name: "复制全文" })).not.toBeInTheDocument();
  });
});
