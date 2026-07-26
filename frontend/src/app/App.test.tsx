import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";

const queryMocks = vi.hoisted(() => ({
  bootstrap: vi.fn(),
  sessions: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
}));

vi.mock("../api/queries", () => ({
  useBootstrapQuery: queryMocks.bootstrap,
  useSessionsQuery: queryMocks.sessions,
  useCreateSessionMutation: queryMocks.createSession,
  useDeleteSessionMutation: queryMocks.deleteSession,
}));

vi.mock("../chat/ChatView", () => ({
  ChatView: ({ session }: { session: { sessionId: number } | null }) => (
    <div>chat session:{session?.sessionId ?? "none"}</div>
  ),
}));

vi.mock("../sessions/SessionSidebar", () => ({
  SessionSidebar: () => <div>session sidebar</div>,
}));

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryMocks.createSession.mockReturnValue({
      isPending: false,
      isError: false,
      mutate: vi.fn(),
      reset: vi.fn(),
    });
    queryMocks.deleteSession.mockReturnValue({
      isPending: false,
      isError: false,
      mutateAsync: vi.fn().mockResolvedValue(undefined),
      reset: vi.fn(),
    });
  });

  it("retries both startup queries from the connection error state", async () => {
    const user = userEvent.setup();
    const refetchBootstrap = vi.fn();
    const refetchSessions = vi.fn();
    queryMocks.bootstrap.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      isFetching: false,
      refetch: refetchBootstrap,
    });
    queryMocks.sessions.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      isFetching: false,
      refetch: refetchSessions,
    });

    render(<App />);
    await user.click(screen.getByRole("button", { name: "重试连接" }));

    expect(refetchBootstrap).toHaveBeenCalledOnce();
    expect(refetchSessions).toHaveBeenCalledOnce();
  });

  it("falls back to the first remaining session and syncs the URL after the selected session disappears", () => {
    window.history.replaceState(null, "", "/?session=8");
    queryMocks.bootstrap.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    });
    const makeSession = (sessionId: number) => ({
      sessionId,
      userId: 1,
      title: `会话 ${sessionId}`,
      metadata: {},
      createdAt: "2026-07-26T08:00:00+08:00",
      updatedAt: "2026-07-26T08:00:00+08:00",
    });
    let rows = [makeSession(7), makeSession(8)];
    queryMocks.sessions.mockImplementation(() => ({
      data: rows,
      isPending: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    }));

    const { rerender } = render(<App />);
    expect(screen.getByText("chat session:8")).toBeInTheDocument();

    // 模拟删除成功后 sessions 缓存被过滤：选中 id 8 不在列表，回落到第一个剩余会话。
    rows = [makeSession(7)];
    rerender(<App />);
    expect(screen.getByText("chat session:7")).toBeInTheDocument();
    expect(new URL(window.location.href).searchParams.get("session")).toBe("7");

    // 删除最后一个会话后进入无会话空态，不崩溃。
    rows = [];
    rerender(<App />);
    expect(screen.getByText("chat session:none")).toBeInTheDocument();
  });
});
