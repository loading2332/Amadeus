import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";

import type { SessionSummary } from "./contracts";
import { useDeleteSessionMutation } from "./queries";
import { queryKeys } from "./queryKeys";

const apiMock = vi.hoisted(() => ({
  deleteSession: vi.fn(),
}));

vi.mock("./client", () => ({ api: apiMock }));

function makeSession(sessionId: number): SessionSummary {
  return {
    sessionId,
    userId: 1,
    title: `会话 ${sessionId}`,
    metadata: {},
    createdAt: "2026-07-26T08:00:00+08:00",
    updatedAt: "2026-07-26T08:00:00+08:00",
  };
}

function renderWithClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useDeleteSessionMutation(), { wrapper }) };
}

describe("useDeleteSessionMutation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("removes the session from the sessions cache and drops its detail caches", async () => {
    apiMock.deleteSession.mockResolvedValue(undefined);
    const { client, result } = renderWithClient();
    client.setQueryData(queryKeys.sessions, [makeSession(7), makeSession(8)]);
    client.setQueryData(queryKeys.messages(7), []);
    client.setQueryData(queryKeys.turns(7), []);

    result.current.mutate(7);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock.deleteSession).toHaveBeenCalledWith(7);
    expect(client.getQueryData(queryKeys.sessions)).toEqual([makeSession(8)]);
    expect(client.getQueryState(queryKeys.messages(7))).toBeUndefined();
    expect(client.getQueryState(queryKeys.turns(7))).toBeUndefined();
  });

  it("keeps the caches untouched when deletion fails", async () => {
    apiMock.deleteSession.mockRejectedValue(new Error("删除失败"));
    const { client, result } = renderWithClient();
    client.setQueryData(queryKeys.sessions, [makeSession(7)]);
    client.setQueryData(queryKeys.turns(7), []);

    result.current.mutate(7);

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(client.getQueryData(queryKeys.sessions)).toEqual([makeSession(7)]);
    expect(client.getQueryState(queryKeys.turns(7))).toBeDefined();
  });
});
