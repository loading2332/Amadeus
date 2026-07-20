import { useEffect, useMemo, useState } from "react";
import AddRounded from "@mui/icons-material/AddRounded";
import MenuRounded from "@mui/icons-material/MenuRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { SessionSummary } from "../api/contracts";
import { useCancelTurnMutation, useCreateTurnMutation, useSessionTurnsQuery } from "../api/queries";
import { turnStreamManager } from "../app/streamManager";
import { Composer } from "./Composer";
import { TurnTimeline } from "./TurnTimeline";

interface Props {
  session: SessionSummary | null;
  desktopSidebarCollapsed: boolean;
  creatingSession: boolean;
  createSessionFailed: boolean;
  onOpenSessions: () => void;
  onOpenDesktopSidebar: () => void;
  onCreateSession: () => void;
}

const ACTIVE = new Set(["pending", "processing", "finalizing"]);

export function ChatView({
  session,
  desktopSidebarCollapsed,
  creatingSession,
  createSessionFailed,
  onOpenSessions,
  onOpenDesktopSidebar,
  onCreateSession,
}: Props) {
  const turns = useSessionTurnsQuery(session?.sessionId ?? null);
  const createTurn = useCreateTurnMutation();
  const cancelTurn = useCancelTurnMutation();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const rows = useMemo(() => turns.data ?? [], [turns.data]);
  const activeTurn = [...rows].reverse().find((turn) => ACTIVE.has(turn.status)) ?? null;

  useEffect(() => {
    if (session === null) return;
    for (const turn of rows) turnStreamManager.connect(turn.turnId, session.sessionId);
  }, [rows, session]);

  const navigationActions = (
    <Box sx={{ position: "absolute", top: 12, left: 12, zIndex: 2 }}>
      <Tooltip title="打开会话列表">
        <IconButton
          aria-label="打开会话列表"
          onClick={onOpenSessions}
          sx={{ display: { md: "none" }, bgcolor: "background.default", "&:hover": { bgcolor: "action.hover" } }}
        >
          <MenuRounded />
        </IconButton>
      </Tooltip>
      {desktopSidebarCollapsed ? (
        <Stack
          data-testid="desktop-collapsed-actions"
          direction="row"
          spacing={0.5}
          sx={{ display: { xs: "none", md: "flex" } }}
        >
          <Tooltip title="展开侧边栏">
            <IconButton aria-label="展开侧边栏" onClick={onOpenDesktopSidebar} sx={{ bgcolor: "background.default", "&:hover": { bgcolor: "action.hover" } }}><MenuRounded /></IconButton>
          </Tooltip>
          <Tooltip title="新对话">
            <span>
              <IconButton aria-label="新对话" disabled={creatingSession} onClick={onCreateSession} sx={{ bgcolor: "background.default", "&:hover": { bgcolor: "action.hover" } }}>
                {creatingSession ? <CircularProgress size={20} color="inherit" /> : <AddRounded />}
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
      ) : null}
      {desktopSidebarCollapsed && createSessionFailed ? (
        <Stack
          role="alert"
          direction="row"
          sx={{ mt: 0.75, px: 1, minHeight: 32, alignItems: "center", gap: 0.5, bgcolor: "background.default" }}
        >
          <Typography variant="caption" color="error.main">
            新对话创建失败
          </Typography>
          <Button aria-label="重试新建" size="small" onClick={onCreateSession}>
            重试
          </Button>
        </Stack>
      ) : null}
    </Box>
  );

  if (session === null) {
    return <Box sx={{ position: "relative", display: "grid", height: "100%", minHeight: 0, gridTemplateRows: "minmax(0, 1fr)", overflow: "hidden" }}>{navigationActions}<EmptyState title="创建一个新对话" detail="从左侧的新对话开始与 Amadeus 交流。" /></Box>;
  }

  const draft = drafts[session.sessionId] ?? "";
  return (
    <Box sx={{ position: "relative", display: "grid", height: "100%", minHeight: 0, gridTemplateRows: "minmax(0, 1fr) auto", overflow: "hidden" }}>
      {navigationActions}
      <TurnTimeline
        key={session.sessionId}
        sessionId={session.sessionId}
        rows={rows}
        pending={turns.isPending}
        failed={turns.isError}
        retrying={turns.isFetching}
        onRetry={() => { void turns.refetch(); }}
        desktopSidebarCollapsed={desktopSidebarCollapsed}
        submittingFirstTurn={rows.length === 0 && createTurn.isPending}
      />
      <Composer
        value={draft}
        busy={createTurn.isPending}
        activeTurn={activeTurn}
        cancelling={cancelTurn.isPending}
        sendFailed={createTurn.isError && createTurn.variables?.sessionId === session.sessionId}
        onChange={(value) => {
          if (createTurn.isError) createTurn.reset();
          setDrafts((current) => ({ ...current, [session.sessionId]: value }));
        }}
        onSend={(message) => {
          createTurn.mutate(
            { sessionId: session.sessionId, message },
            {
              onSuccess: (turn) => {
                setDrafts((current) => ({ ...current, [session.sessionId]: "" }));
                turnStreamManager.connect(turn.turnId, session.sessionId);
              },
            },
          );
        }}
        onStop={() => activeTurn !== null && cancelTurn.mutate(activeTurn.turnId)}
      />
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
