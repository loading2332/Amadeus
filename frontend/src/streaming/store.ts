import { create } from "zustand";

import type { StreamConnection, TurnStreamState } from "./reducer";
import { initialTurnStream, reduceTurnEvent } from "./reducer";
import type { TurnEvent } from "./events";

interface LiveTurnStore {
  turns: Record<string, TurnStreamState>;
  ensureTurn: (turnId: string, sessionId: number) => void;
  applyEvent: (event: TurnEvent) => void;
  setConnection: (turnId: string, connection: StreamConnection) => void;
  setStreamError: (turnId: string, message: string) => void;
  removeTurn: (turnId: string) => void;
  reset: () => void;
}

export const useLiveTurnStore = create<LiveTurnStore>((set) => ({
  turns: {},
  ensureTurn: (turnId, sessionId) =>
    set((state) =>
      state.turns[turnId] === undefined
        ? { turns: { ...state.turns, [turnId]: initialTurnStream(turnId, sessionId) } }
        : state,
    ),
  applyEvent: (event) =>
    set((state) => {
      const current = state.turns[event.turnId];
      if (current === undefined) return state;
      const next = reduceTurnEvent(current, event);
      return next === current
        ? state
        : { turns: { ...state.turns, [event.turnId]: next } };
    }),
  setConnection: (turnId, connection) =>
    set((state) => {
      const current = state.turns[turnId];
      if (current === undefined || current.connection === connection) return state;
      return {
        turns: { ...state.turns, [turnId]: { ...current, connection } },
      };
    }),
  setStreamError: (turnId, message) =>
    set((state) => {
      const current = state.turns[turnId];
      if (current === undefined || current.streamError === message) return state;
      return {
        turns: {
          ...state.turns,
          [turnId]: { ...current, streamError: message, connection: "closed" },
        },
      };
    }),
  removeTurn: (turnId) =>
    set((state) => {
      if (state.turns[turnId] === undefined) return state;
      const turns = { ...state.turns };
      delete turns[turnId];
      return { turns };
    }),
  reset: () => set({ turns: {} }),
}));
