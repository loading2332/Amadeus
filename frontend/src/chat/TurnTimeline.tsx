import { useLayoutEffect, useRef, useState } from "react";
import ArrowDownwardRounded from "@mui/icons-material/ArrowDownwardRounded";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { Turn } from "../api/contracts";
import { useLiveTurnStore } from "../streaming/store";
import { TurnItem } from "./TurnItem";

const BOTTOM_THRESHOLD = 96;
const BOTTOM_EPSILON = 2;

interface Props {
  sessionId: number;
  rows: Turn[];
  pending: boolean;
  failed: boolean;
  retrying: boolean;
  onRetry: () => void;
  desktopSidebarCollapsed: boolean;
  submittingFirstTurn: boolean;
}

export function TurnTimeline({
  sessionId,
  rows,
  pending,
  failed,
  retrying,
  onRetry,
  desktopSidebarCollapsed,
  submittingFirstTurn,
}: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);
  const returningToBottomRef = useRef(false);
  const [following, setFollowing] = useState(true);
  const showWelcome = rows.length === 0 && !submittingFirstTurn;
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
        onScroll={(event) => {
          const element = event.currentTarget;
          if (returningToBottomRef.current) {
            if (isAtBottom(element)) {
              returningToBottomRef.current = false;
              updateFollowing(true);
            }
            return;
          }
          updateFollowing(isNearBottom(element));
        }}
        sx={{
          height: "100%",
          overflowY: "auto",
          overflowX: "hidden",
          overscrollBehavior: "contain",
        }}
      >
        {pending || failed || showWelcome ? (
          <Box
            data-testid="timeline-state"
            sx={{
              width: "100%",
              minHeight: "100%",
              display: "grid",
              placeItems: "center",
              px: { xs: 2, sm: 4 },
            }}
          >
            {pending ? (
              <EmptyState title="正在载入对话" detail="">
                <CircularProgress size={24} />
              </EmptyState>
            ) : failed ? (
              <EmptyState
                title="无法载入对话"
                detail="暂时无法获取消息。"
                action={
                  <Button
                    size="small"
                    startIcon={retrying ? <CircularProgress size={14} color="inherit" /> : <RefreshRounded />}
                    disabled={retrying}
                    onClick={onRetry}
                  >
                    {retrying ? "正在载入" : "重新载入"}
                  </Button>
                }
              />
            ) : (
              <EmptyState
                title="有什么想一起完成的？"
                detail="输入消息后，Amadeus 会在这里实时回答。"
              />
            )}
          </Box>
        ) : (
          <Box
            sx={{
              width: "100%",
              maxWidth: 900,
              mx: "auto",
              px: { xs: 2, sm: 4 },
              pt: { xs: 9, md: desktopSidebarCollapsed ? 9 : 5 },
              pb: { xs: 3, sm: 5 },
            }}
          >
            <Stack spacing={{ xs: 4, md: 6 }}>
              {rows.map((turn) => (
                <TurnItem key={turn.turnId} turn={turn} />
              ))}
            </Stack>
          </Box>
        )}
      </Box>
      {!following ? (
        <IconButton
          aria-label="回到底部"
          disableRipple
          onClick={() => {
            returningToBottomRef.current = true;
            scrollToBottom(viewport.current, "smooth");
          }}
          sx={{
            position: "absolute",
            left: "50%",
            bottom: 16,
            width: 40,
            height: 40,
            transform: "translateX(-50%)",
            bgcolor: "primary.main",
            color: "primary.contrastText",
            boxShadow: 2,
            "&:hover": { bgcolor: "primary.main", opacity: 0.9 },
          }}
        >
          <ArrowDownwardRounded fontSize="small" />
        </IconButton>
      ) : null}
    </Box>
  );
}

function EmptyState({
  title,
  detail,
  children,
  action,
}: {
  title: string;
  detail: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <Stack
      data-testid="timeline-state-content"
      sx={{ alignItems: "center", textAlign: "center" }}
      spacing={1}
    >
      {children}
      <Typography variant="h6">{title}</Typography>
      {detail ? <Typography color="text.secondary">{detail}</Typography> : null}
      {action}
    </Stack>
  );
}

function isNearBottom(element: HTMLElement): boolean {
  return getBottomGap(element) <= BOTTOM_THRESHOLD;
}

function isAtBottom(element: HTMLElement): boolean {
  return getBottomGap(element) <= BOTTOM_EPSILON;
}

function getBottomGap(element: HTMLElement): number {
  return element.scrollHeight - element.scrollTop - element.clientHeight;
}

function scrollToBottom(
  element: HTMLElement | null,
  behavior: ScrollBehavior,
): void {
  if (element === null) return;
  element.scrollTo({ top: element.scrollHeight, behavior });
}
