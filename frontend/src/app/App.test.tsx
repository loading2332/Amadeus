import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";

const queryMocks = vi.hoisted(() => ({
  bootstrap: vi.fn(),
  sessions: vi.fn(),
  createSession: vi.fn(),
}));

vi.mock("../api/queries", () => ({
  useBootstrapQuery: queryMocks.bootstrap,
  useSessionsQuery: queryMocks.sessions,
  useCreateSessionMutation: queryMocks.createSession,
}));

vi.mock("../chat/ChatView", () => ({
  ChatView: () => <div>chat view</div>,
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
});
