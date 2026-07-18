export type TurnStatus =
  | "pending"
  | "processing"
  | "finalizing"
  | "done"
  | "failed"
  | "cancelled";

export interface Bootstrap {
  ownerUserId: number;
}

export interface SessionSummary {
  sessionId: number;
  userId: number;
  title: string | null;
  metadata: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface Message {
  id: string;
  userId: number | null;
  sessionId: number | null;
  seq: number;
  role: string;
  content: string;
  timestamp: string | null;
}

export interface Turn {
  turnId: string;
  userId: number;
  sessionId: number;
  content: string;
  status: TurnStatus;
  answer: string | null;
  partialAnswer: string;
  streamVersion: number;
  retryOfTurnId: string | null;
  error: TurnError | null;
  metadata: Record<string, unknown>;
  createdAt: string | null;
  updatedAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface TurnError {
  code: string;
  message: string;
  retryable: boolean;
}

const TURN_STATUSES = new Set<TurnStatus>([
  "pending",
  "processing",
  "finalizing",
  "done",
  "failed",
  "cancelled",
]);

export function decodeBootstrap(value: unknown): Bootstrap {
  const row = record(value, "bootstrap");
  return { ownerUserId: positiveInteger(row.owner_user_id, "owner_user_id") };
}

export function decodeSessions(value: unknown): SessionSummary[] {
  return array(value, "sessions").map(decodeSession);
}

export function decodeSession(value: unknown): SessionSummary {
  const row = record(value, "session");
  return {
    sessionId: positiveInteger(row.session_id, "session_id"),
    userId: positiveInteger(row.user_id, "user_id"),
    title: nullableString(row.title, "title"),
    metadata: optionalRecord(row.metadata, "metadata"),
    createdAt: nullableString(row.created_at, "created_at"),
    updatedAt: nullableString(row.updated_at, "updated_at"),
  };
}

export function decodeMessages(value: unknown): Message[] {
  return array(value, "messages").map((item) => {
    const row = record(item, "message");
    return {
      id: string(row.id, "id"),
      userId: nullablePositiveInteger(row.user_id, "user_id"),
      sessionId: nullablePositiveInteger(row.session_id, "session_id"),
      seq: nonNegativeInteger(row.seq, "seq"),
      role: string(row.role, "role"),
      content: string(row.content, "content"),
      timestamp: nullableString(row.timestamp, "timestamp"),
    };
  });
}

export function decodeTurns(value: unknown): Turn[] {
  return array(value, "turns").map(decodeTurn);
}

export function decodeTurn(value: unknown): Turn {
  const row = record(value, "turn");
  const status = string(row.status, "status");
  if (!TURN_STATUSES.has(status as TurnStatus)) {
    throw new ContractError(`status has unsupported value: ${status}`);
  }
  const errorCode = nullableString(row.error_code, "error_code");
  const errorMessage = nullableString(row.error_message, "error_message");
  const errorRetryable = nullableBoolean(row.error_retryable, "error_retryable");
  return {
    turnId: string(row.turn_id, "turn_id"),
    userId: positiveInteger(row.user_id, "user_id"),
    sessionId: positiveInteger(row.session_id, "session_id"),
    content: string(row.content, "content"),
    status: status as TurnStatus,
    answer: nullableString(row.answer, "answer"),
    partialAnswer: string(row.partial_answer, "partial_answer"),
    streamVersion: nonNegativeInteger(row.stream_version, "stream_version"),
    retryOfTurnId: nullableString(row.retry_of_turn_id, "retry_of_turn_id"),
    error:
      errorCode !== null && errorMessage !== null && errorRetryable !== null
        ? { code: errorCode, message: errorMessage, retryable: errorRetryable }
        : null,
    metadata: optionalRecord(row.metadata, "metadata"),
    createdAt: nullableString(row.created_at, "created_at"),
    updatedAt: nullableString(row.updated_at, "updated_at"),
    startedAt: nullableString(row.started_at, "started_at"),
    finishedAt: nullableString(row.finished_at, "finished_at"),
  };
}

export class ContractError extends Error {
  constructor(message: string) {
    super(`Invalid API response: ${message}`);
    this.name = "ContractError";
  }
}

export function record(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ContractError(`${field} must be an object`);
  }
  return value as Record<string, unknown>;
}

export function string(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new ContractError(`${field} must be a string`);
  }
  return value;
}

function array(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new ContractError(`${field} must be an array`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null || value === undefined ? null : string(value, field);
}

function positiveInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    throw new ContractError(`${field} must be a positive integer`);
  }
  return value;
}

function nullablePositiveInteger(value: unknown, field: string): number | null {
  return value === null || value === undefined ? null : positiveInteger(value, field);
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ContractError(`${field} must be a non-negative integer`);
  }
  return value;
}

function nullableBoolean(value: unknown, field: string): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "boolean") {
    throw new ContractError(`${field} must be a boolean`);
  }
  return value;
}

function optionalRecord(value: unknown, field: string): Record<string, unknown> {
  return value === undefined || value === null ? {} : record(value, field);
}
