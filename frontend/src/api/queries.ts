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

export function useCreateSessionMutation(): UseMutationResult<SessionSummary, Error, void> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.createSession(),
    onSuccess: (session) => {
      client.setQueryData<SessionSummary[]>(queryKeys.sessions, (current = []) => [
        session,
        ...current.filter((item) => item.sessionId !== session.sessionId),
      ]);
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
