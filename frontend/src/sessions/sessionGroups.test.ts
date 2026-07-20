import type { SessionSummary } from "../api/contracts";
import { groupSessionsByDate } from "./sessionGroups";

const now = new Date(2026, 6, 19, 12, 0, 0);

describe("groupSessionsByDate", () => {
  it("groups sessions by local calendar day and preserves their order", () => {
    const sessions = [
      session(1, new Date(2026, 6, 19, 8).toISOString()),
      session(2, new Date(2026, 6, 18, 23, 59).toISOString()),
      session(3, new Date(2026, 5, 30, 12).toISOString()),
      session(4, new Date(2026, 6, 19, 7).toISOString()),
    ];

    expect(groupSessionsByDate(sessions, now).map((group) => ({
      key: group.key,
      label: group.label,
      ids: group.sessions.map((row) => row.sessionId),
    }))).toEqual([
      { key: "today", label: "今天", ids: [1, 4] },
      { key: "yesterday", label: "昨天", ids: [2] },
      { key: "earlier", label: "更早", ids: [3] },
    ]);
  });

  it("uses createdAt only when updatedAt is absent", () => {
    const row = session(1, null, new Date(2026, 6, 18, 9).toISOString());
    expect(groupSessionsByDate([row], now)[0]?.key).toBe("yesterday");

    const invalidUpdate = { ...row, updatedAt: "invalid" };
    expect(groupSessionsByDate([invalidUpdate], now)[0]?.key).toBe("earlier");
  });

  it("places missing, invalid, and future timestamps in earlier", () => {
    const sessions = [
      session(1, null),
      session(2, "invalid"),
      session(3, new Date(2026, 6, 20, 8).toISOString()),
    ];

    const groups = groupSessionsByDate(sessions, now);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBe("earlier");
    expect(groups[0]?.sessions).toEqual(sessions);
  });

  it("omits empty groups", () => {
    expect(groupSessionsByDate([], now)).toEqual([]);
  });
});

function session(
  sessionId: number,
  updatedAt: string | null,
  createdAt: string | null = null,
): SessionSummary {
  return {
    sessionId,
    userId: 1,
    title: `会话 ${sessionId}`,
    metadata: {},
    createdAt,
    updatedAt,
  };
}
