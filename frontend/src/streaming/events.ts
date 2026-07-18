import { record, string, ContractError, type TurnError, type TurnStatus } from "../api/contracts";

export type ToolActivityState = "started" | "completed" | "failed";

interface EventBase {
  seq: number;
  turnId: string;
  occurredAt: string;
}

export interface ContentSnapshotEvent extends EventBase {
  type: "content_snapshot";
  content: string;
  version: number;
}

export interface ToolActivityEvent extends EventBase {
  type: "tool_activity";
  activityId: string;
  toolName: string;
  state: ToolActivityState;
}

export interface TurnStatusEvent extends EventBase {
  type: "turn_status";
  status: TurnStatus;
}

export interface TurnTerminalEvent extends EventBase {
  type: "turn_terminal";
  status: Extract<TurnStatus, "done" | "failed" | "cancelled">;
  error: TurnError | null;
}

export type TurnEvent =
  | ContentSnapshotEvent
  | ToolActivityEvent
  | TurnStatusEvent
  | TurnTerminalEvent;

const TURN_STATUSES = new Set<TurnStatus>([
  "pending",
  "processing",
  "finalizing",
  "done",
  "failed",
  "cancelled",
]);
const TERMINAL_STATUSES = new Set(["done", "failed", "cancelled"] as const);
const TOOL_STATES = new Set<ToolActivityState>(["started", "completed", "failed"]);

export function decodeTurnEvent(value: unknown): TurnEvent {
  const envelope = record(value, "turn event");
  const seq = integer(envelope.seq, "seq");
  const turnId = string(envelope.turn_id, "turn_id");
  const occurredAt = string(envelope.occurred_at, "occurred_at");
  const type = string(envelope.type, "type");
  const data = record(envelope.data, "data");
  const base = { seq, turnId, occurredAt };

  switch (type) {
    case "content_snapshot":
      return {
        ...base,
        type,
        content: string(data.content, "data.content"),
        version: integer(data.version, "data.version"),
      };
    case "tool_activity": {
      const state = string(data.state, "data.state");
      if (!TOOL_STATES.has(state as ToolActivityState)) {
        throw new ContractError(`data.state has unsupported value: ${state}`);
      }
      return {
        ...base,
        type,
        activityId: string(data.activity_id, "data.activity_id"),
        toolName: string(data.tool_name, "data.tool_name"),
        state: state as ToolActivityState,
      };
    }
    case "turn_status":
      return { ...base, type, status: turnStatus(data.status) };
    case "turn_terminal": {
      const status = turnStatus(data.status);
      if (!TERMINAL_STATUSES.has(status as "done" | "failed" | "cancelled")) {
        throw new ContractError(`terminal status has unsupported value: ${status}`);
      }
      return {
        ...base,
        type,
        status: status as "done" | "failed" | "cancelled",
        error: decodeTerminalError(data.error),
      };
    }
    default:
      throw new ContractError(`event type has unsupported value: ${type}`);
  }
}

function turnStatus(value: unknown): TurnStatus {
  const status = string(value, "data.status");
  if (!TURN_STATUSES.has(status as TurnStatus)) {
    throw new ContractError(`data.status has unsupported value: ${status}`);
  }
  return status as TurnStatus;
}

function integer(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ContractError(`${field} must be a non-negative integer`);
  }
  return value;
}

function decodeTerminalError(value: unknown): TurnError | null {
  if (value === undefined || value === null) return null;
  const error = record(value, "data.error");
  if (typeof error.retryable !== "boolean") {
    throw new ContractError("data.error.retryable must be a boolean");
  }
  return {
    code: string(error.error_code, "data.error.error_code"),
    message: string(error.message, "data.error.message"),
    retryable: error.retryable,
  };
}
