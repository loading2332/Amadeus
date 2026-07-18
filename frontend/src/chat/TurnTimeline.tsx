import { useLayoutEffect, useRef, useState } from "react";
import ArrowDownwardRounded from "@mui/icons-material/ArrowDownwardRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { Turn } from "../api/contracts";
import { useLiveTurnStore } from "../streaming/store";
import { TurnItem } from "./TurnItem";

const BOTTOM_THRESHOLD = 96;

interface Props {
  sessionId: number;
  rows: Turn[];
  pending: boolean;
  failed: boolean;
}

export function TurnTimeline({ sessionId, rows, pending, failed }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);
  const [following, setFollowing] = useState(true);
  const streamSignal = useLiveTurnStore((state) =>
    rows.map((turn) => state.turns[turn.turnId]?.lastSeq ?? 0).join(":"),
  );

  useLayoutEffect(() => {
    scrollToBottom(viewport.current, "auto");
  }, [sessionId]);

  useLayoutEffect(() => {
    if (followingRef.current) scrollToBottom(viewport.current, "auto");
  }, [rows.length, streamSignal]);

  const updateFollowing = (next: boolean) => {
    followingRef.current = next;
    setFollowing(next);
  };

  return (
    <Box sx={{ position: "relative", minHeight: 0, overflow: "hidden" }}>
      <Box
        ref={viewport}
        data-testid="chat-timeline"
        onScroll={(event) => updateFollowing(isNearBottom(event.currentTarget))}
        sx={{ height: "100%", overflowY: "auto", overflowX: "hidden", overscrollBehavior: "contain" }}
      >
        <Box sx={{ width: "100%", maxWidth: 900, mx: "auto", px: { xs: 2, sm: 4 }, py: { xs: 3, sm: 5 } }}>
          {pending ? (
            <EmptyState title="正在载入对话" detail=""><CircularProgress size={24} /></EmptyState>
          ) : failed ? (
            <EmptyState title="无法载入对话" detail="请检查连接后刷新页面。" />
          ) : rows.length === 0 ? (
            <EmptyState title="开始新对话" detail="发送一条文本消息，Amadeus 会在这里流式回答。" />
          ) : (
            <Stack spacing={4}>{rows.map((turn) => <TurnItem key={turn.turnId} turn={turn} />)}</Stack>
          )}
        </Box>
      </Box>
      {!following ? (
        <Button
          size="small"
          variant="contained"
          startIcon={<ArrowDownwardRounded />}
          onClick={() => {
            updateFollowing(true);
            scrollToBottom(viewport.current, "smooth");
          }}
          sx={{ position: "absolute", right: { xs: 16, sm: 32 }, bottom: 16 }}
        >
          回到底部
        </Button>
      ) : null}
    </Box>
  );
}

function EmptyState({ title, detail, children }: { title: string; detail: string; children?: React.ReactNode }) {
  return (
    <Stack sx={{ minHeight: 240, alignItems: "center", justifyContent: "center", textAlign: "center" }} spacing={1}>
      {children}<Typography variant="h6">{title}</Typography>{detail ? <Typography color="text.secondary">{detail}</Typography> : null}
    </Stack>
  );
}

function isNearBottom(element: HTMLElement): boolean {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= BOTTOM_THRESHOLD;
}

function scrollToBottom(element: HTMLElement | null, behavior: ScrollBehavior): void {
  if (element === null) return;
  element.scrollTo({ top: element.scrollHeight, behavior });
}
