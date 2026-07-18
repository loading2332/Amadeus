import type { TurnError, TurnStatus } from "../api/contracts";
import type { ToolActivityState, TurnEvent } from "./events";

export interface TextPart {
  kind: "text";
  id: string;
  content: string;
}

export interface ToolPart {
  kind: "tool";
  id: string;
  activityId: string;
  toolName: string;
  state: ToolActivityState;
  collapsed: boolean;
}

export type StreamPart = TextPart | ToolPart;
export type StreamConnection = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export interface TurnStreamState {
  turnId: string;
  sessionId: number;
  lastSeq: number;
  snapshot: string;
  status: TurnStatus;
  error: TurnError | null;
  streamError: string | null;
  connection: StreamConnection;
  parts: StreamPart[];
}

export function initialTurnStream(turnId: string, sessionId: number): TurnStreamState {
  return {
    turnId,
    sessionId,
    lastSeq: 0,
    snapshot: "",
    status: "pending",
    error: null,
    streamError: null,
    connection: "idle",
    parts: [],
  };
}

export function reduceTurnEvent(state: TurnStreamState, event: TurnEvent): TurnStreamState {
  if (event.turnId !== state.turnId || event.seq <= state.lastSeq) return state;

  switch (event.type) {
    case "content_snapshot":
      return reduceSnapshot(state, event.seq, event.content);
    case "tool_activity":
      return {
        ...state,
        lastSeq: event.seq,
        parts: updateToolPart(state.parts, event),
      };
    case "turn_status":
      return { ...state, lastSeq: event.seq, status: event.status };
    case "turn_terminal":
      return {
        ...state,
        lastSeq: event.seq,
        status: event.status,
        error: event.error,
        connection: "closed",
      };
  }
}

function reduceSnapshot(state: TurnStreamState, seq: number, content: string): TurnStreamState {
  if (!content.startsWith(state.snapshot)) {
    return {
      ...state,
      lastSeq: seq,
      snapshot: content,
      parts: content === "" ? [] : [{ kind: "text", id: `text:${seq}`, content }],
    };
  }
  const delta = content.slice(state.snapshot.length);
  if (delta === "") return { ...state, lastSeq: seq, snapshot: content };
  const parts = [...state.parts];
  const last = parts.at(-1);
  if (last?.kind === "text") {
    parts[parts.length - 1] = { ...last, content: last.content + delta };
  } else {
    parts.push({ kind: "text", id: `text:${seq}`, content: delta });
  }
  return { ...state, lastSeq: seq, snapshot: content, parts };
}

function updateToolPart(
  parts: StreamPart[],
  event: Extract<TurnEvent, { type: "tool_activity" }>,
): StreamPart[] {
  const index = parts.findIndex(
    (part) => part.kind === "tool" && part.activityId === event.activityId,
  );
  const tool: ToolPart = {
    kind: "tool",
    id: `tool:${event.activityId}`,
    activityId: event.activityId,
    toolName: event.toolName,
    state: event.state,
    collapsed: event.state !== "started",
  };
  if (index === -1) return [...parts, tool];
  const next = [...parts];
  next[index] = tool;
  return next;
}
