import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { api } from "./client";
import type { SessionSummary, Turn } from "./contracts";
import { queryKeys } from "./queryKeys";

export function useBootstrapQuery() {
  return useQuery({
    queryKey: queryKeys.bootstrap,
    queryFn: ({ signal }) => api.getBootstrap(signal),
  });
}

export function useSessionsQuery() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: ({ signal }) => api.listSessions(signal),
  });
}

export function useSessionMessagesQuery(sessionId: number | null) {
  return useQuery({
    queryKey: sessionId === null ? ["session-messages", "none"] : queryKeys.messages(sessionId),
    queryFn: ({ signal }) => api.listMessages(requireSessionId(sessionId), signal),
    enabled: sessionId !== null,
  });
}

export function useSessionTurnsQuery(sessionId: number | null) {
  return useQuery({
    queryKey: sessionId === null ? ["session-turns", "none"] : queryKeys.turns(sessionId),
    queryFn: ({ signal }) => api.listTurns(requireSessionId(sessionId), signal),
    enabled: sessionId !== null,
  });
}

export function useCreateSessionMutation(
  onCreated?: (session: SessionSummary) => void,
): UseMutationResult<SessionSummary, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.createSession(),
    onSuccess: (session) => {
      // 选中态必须先于列表缓存更新，两者才会合并进同一次渲染；
      // 反过来会先渲染"新会话插入但选中还在旧行"的中间帧，高亮闪跳。
      onCreated?.(session);
      client.setQueryData<SessionSummary[]>(queryKeys.sessions, (current = []) => [
        session,
        ...current.filter((item) => item.sessionId !== session.sessionId),
      ]);
    },
  });
}

export function useDeleteSessionMutation(): UseMutationResult<void, Error, number> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (sessionId) => api.deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      client.setQueryData<SessionSummary[]>(queryKeys.sessions, (current = []) =>
        current.filter((item) => item.sessionId !== sessionId),
      );
      client.removeQueries({ queryKey: queryKeys.messages(sessionId) });
      client.removeQueries({ queryKey: queryKeys.turns(sessionId) });
    },
  });
}

interface CreateTurnVariables {
  sessionId: number;
  message: string;
}

export function useCreateTurnMutation(): UseMutationResult<Turn, Error, CreateTurnVariables> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, message }) => api.createTurn(sessionId, message),
    onSuccess: (turn) => {
      upsertTurn(client, turn);
      void client.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });
}

export function useCancelTurnMutation(): UseMutationResult<Turn, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (turnId) => api.cancelTurn(turnId),
    onSuccess: (turn) => upsertTurn(client, turn),
  });
}

export function useRetryTurnMutation(): UseMutationResult<Turn, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (turnId) => api.retryTurn(turnId),
    onSuccess: (turn) => upsertTurn(client, turn),
  });
}

function upsertTurn(
  client: ReturnType<typeof useQueryClient>,
  turn: Turn,
): void {
  client.setQueryData(queryKeys.turn(turn.turnId), turn);
  client.setQueryData<Turn[]>(queryKeys.turns(turn.sessionId), (current = []) => {
    const index = current.findIndex((item) => item.turnId === turn.turnId);
    if (index === -1) return [...current, turn];
    const next = [...current];
    next[index] = turn;
    return next;
  });
}

function requireSessionId(sessionId: number | null): number {
  if (sessionId === null) throw new Error("sessionId is required");
  return sessionId;
}
