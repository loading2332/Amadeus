import type { SessionSummary } from "../api/contracts";

export type SessionGroupKey = "today" | "yesterday" | "earlier";

export interface SessionGroup {
  key: SessionGroupKey;
  label: string;
  sessions: SessionSummary[];
}

const GROUPS: ReadonlyArray<{ key: SessionGroupKey; label: string }> = [
  { key: "today", label: "今天" },
  { key: "yesterday", label: "昨天" },
  { key: "earlier", label: "更早" },
];
const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;

export function groupSessionsByDate(
  sessions: SessionSummary[],
  now: Date = new Date(),
): SessionGroup[] {
  const buckets: Record<SessionGroupKey, SessionSummary[]> = {
    today: [],
    yesterday: [],
    earlier: [],
  };

  for (const session of sessions) {
    buckets[classifySessionDate(session.updatedAt ?? session.createdAt, now)].push(session);
  }

  return GROUPS.flatMap(({ key, label }) => {
    const rows = buckets[key];
    return rows.length === 0 ? [] : [{ key, label, sessions: rows }];
  });
}

function classifySessionDate(value: string | null, now: Date): SessionGroupKey {
  if (value === null || Number.isNaN(now.getTime())) return "earlier";

  const date = new Date(value);
  if (Number.isNaN(date.getTime()) || date.getTime() > now.getTime()) return "earlier";

  const dayDifference = localDayOrdinal(now) - localDayOrdinal(date);
  if (dayDifference === 0) return "today";
  if (dayDifference === 1) return "yesterday";
  return "earlier";
}

function localDayOrdinal(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / MILLISECONDS_PER_DAY;
}
