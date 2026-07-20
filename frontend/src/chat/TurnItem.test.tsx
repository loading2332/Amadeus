import { render, screen } from "@testing-library/react";

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
});
