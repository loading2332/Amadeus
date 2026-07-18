export const queryKeys = {
  bootstrap: ["bootstrap"] as const,
  sessions: ["sessions"] as const,
  messages: (sessionId: number) => ["session-messages", sessionId] as const,
  turns: (sessionId: number) => ["session-turns", sessionId] as const,
  turn: (turnId: string) => ["turn", turnId] as const,
};
