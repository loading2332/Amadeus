import { render } from "@testing-library/react";

import type { SessionSummary, Turn, TurnStatus } from "../api/contracts";
import { useLiveTurnStore } from "../streaming/store";
import { ChatView } from "./ChatView";

const queryMocks = vi.hoisted(() => ({
  sessionTurns: vi.fn(),
  createTurn: vi.fn(),
  cancelTurn: vi.fn(),
}));

const streamMocks = vi.hoisted(() => ({
  openedUrls: [] as string[],
}));

vi.mock("../api/queries", () => ({
  useSessionTurnsQuery: queryMocks.sessionTurns,
  useCreateTurnMutation: queryMocks.createTurn,
  useCancelTurnMutation: queryMocks.cancelTurn,
}));

vi.mock("../app/streamManager", async () => {
  const { TurnStreamManager } = await import("../streaming/manager");

  class FakeEventSource {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;

    readonly url: string;
    readyState = FakeEventSource.CONNECTING;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;

    constructor(url: string) {
      this.url = url;
    }

    addEventListener(): void {}

    close(): void {
      this.readyState = FakeEventSource.CLOSED;
    }
  }

  return {
    turnStreamManager: new TurnStreamManager(undefined, (url) => {
      streamMocks.openedUrls.push(url);
      return new FakeEventSource(url) as unknown as EventSource;
    }),
  };
});

vi.mock("./TurnTimeline", () => ({
  TurnTimeline: () => <div>turn timeline</div>,
}));

vi.mock("./Composer", () => ({
  Composer: () => <div>composer</div>,
}));

const session: SessionSummary = {
  sessionId: 4,
  userId: 1,
  title: "会话",
  metadata: {},
  createdAt: null,
  updatedAt: null,
};

function makeTurn(turnId: string, status: TurnStatus): Turn {
  return {
    turnId,
    userId: 1,
    sessionId: session.sessionId,
    content: "hi",
    status,
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
}

function renderChatView(rows: Turn[]): void {
  queryMocks.sessionTurns.mockReturnValue({
    data: rows,
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  });
  render(
    <ChatView
      session={session}
      desktopSidebarCollapsed={false}
      creatingSession={false}
      createSessionFailed={false}
      onOpenSessions={vi.fn()}
      onOpenDesktopSidebar={vi.fn()}
      onCreateSession={vi.fn()}
    />,
  );
}

describe("ChatView turn stream connections", () => {
  beforeEach(() => {
    streamMocks.openedUrls.length = 0;
    useLiveTurnStore.getState().reset();
    queryMocks.createTurn.mockReturnValue({
      isPending: false,
      isError: false,
      variables: undefined,
      mutate: vi.fn(),
      reset: vi.fn(),
    });
    queryMocks.cancelTurn.mockReturnValue({
      isPending: false,
      mutate: vi.fn(),
    });
  });

  it("does not open SSE connections for terminal turns", () => {
    renderChatView([
      makeTurn("turn-done", "done"),
      makeTurn("turn-failed", "failed"),
      makeTurn("turn-cancelled", "cancelled"),
      makeTurn("turn-processing", "processing"),
    ]);

    expect(streamMocks.openedUrls).toEqual([
      "/api/turns/turn-processing/events?after_seq=0",
    ]);
  });

  it("opens SSE connections for every active turn status", () => {
    renderChatView([
      makeTurn("turn-pending", "pending"),
      makeTurn("turn-finalizing", "finalizing"),
      makeTurn("turn-settled", "done"),
    ]);

    expect(streamMocks.openedUrls).toEqual([
      "/api/turns/turn-pending/events?after_seq=0",
      "/api/turns/turn-finalizing/events?after_seq=0",
    ]);
  });
});
