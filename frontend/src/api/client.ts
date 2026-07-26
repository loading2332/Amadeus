import axios, { AxiosError, type AxiosInstance } from "axios";

import {
  decodeBootstrap,
  decodeMessages,
  decodeSession,
  decodeSessions,
  decodeTurn,
  decodeTurns,
  record,
  type Bootstrap,
  type Message,
  type SessionSummary,
  type Turn,
} from "./contracts";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number | null,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const http = axios.create({
  baseURL: "/api",
  headers: { Accept: "application/json" },
  timeout: 20_000,
});

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(toApiError(error)),
);

export function createApi(instance: AxiosInstance = http) {
  return {
    async getBootstrap(signal?: AbortSignal): Promise<Bootstrap> {
      const response = await instance.get<unknown>("/bootstrap", { signal });
      return decodeBootstrap(response.data);
    },
    async listSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
      const response = await instance.get<unknown>("/sessions", { signal });
      return decodeSessions(response.data);
    },
    async createSession(signal?: AbortSignal): Promise<SessionSummary> {
      const response = await instance.post<unknown>("/sessions", {}, { signal });
      return decodeSession(response.data);
    },
    async deleteSession(sessionId: number, signal?: AbortSignal): Promise<void> {
      await instance.delete(`/sessions/${encodeURIComponent(sessionId)}`, { signal });
    },
    async listMessages(sessionId: number, signal?: AbortSignal): Promise<Message[]> {
      const response = await instance.get<unknown>(
        `/sessions/${encodeURIComponent(sessionId)}/messages`,
        { signal },
      );
      return decodeMessages(response.data);
    },
    async listTurns(sessionId: number, signal?: AbortSignal): Promise<Turn[]> {
      const response = await instance.get<unknown>(
        `/sessions/${encodeURIComponent(sessionId)}/turns`,
        { signal },
      );
      return decodeTurns(response.data);
    },
    async getTurn(turnId: string, signal?: AbortSignal): Promise<Turn> {
      const response = await instance.get<unknown>(
        `/turns/${encodeURIComponent(turnId)}`,
        { signal },
      );
      return decodeTurn(response.data);
    },
    async createTurn(sessionId: number, message: string, signal?: AbortSignal): Promise<Turn> {
      const response = await instance.post<unknown>(
        "/messages",
        { session_id: sessionId, message },
        { signal },
      );
      return decodeTurn(response.data);
    },
    async cancelTurn(turnId: string, signal?: AbortSignal): Promise<Turn> {
      const response = await instance.post<unknown>(
        `/turns/${encodeURIComponent(turnId)}/cancel`,
        {},
        { signal },
      );
      return decodeTurn(response.data);
    },
    async retryTurn(turnId: string, signal?: AbortSignal): Promise<Turn> {
      const response = await instance.post<unknown>(
        `/turns/${encodeURIComponent(turnId)}/retry`,
        {},
        { signal },
      );
      return decodeTurn(response.data);
    },
  };
}

export const api = createApi();

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (!axios.isAxiosError(error)) {
    return new ApiError("发生未知错误，请重试", "unknown_error", null, true);
  }
  const status = error.response?.status ?? null;
  const safe = safeErrorPayload(error);
  if (safe !== null) {
    return new ApiError(safe.message, safe.code, status, status === null || status >= 500);
  }
  if (error.code === AxiosError.ERR_CANCELED) {
    return new ApiError("请求已取消", "request_cancelled", status, false);
  }
  if (status === null) {
    return new ApiError("无法连接服务器，请检查网络后重试", "network_error", null, true);
  }
  return new ApiError("请求失败，请稍后重试", `http_${status}`, status, status >= 500);
}

function safeErrorPayload(error: AxiosError<unknown>): { code: string; message: string } | null {
  try {
    const payload = record(error.response?.data, "error");
    const code = typeof payload.code === "string" ? payload.code : null;
    const detail = typeof payload.detail === "string" ? payload.detail : null;
    if (detail === null) return null;
    return { code: code ?? `http_${error.response?.status ?? "error"}`, message: detail };
  } catch {
    return null;
  }
}
