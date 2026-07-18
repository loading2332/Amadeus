import { useEffect, useMemo, useState } from "react";
import MenuRounded from "@mui/icons-material/MenuRounded";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { SessionSummary } from "../api/contracts";
import { useCancelTurnMutation, useCreateTurnMutation, useSessionTurnsQuery } from "../api/queries";
import { turnStreamManager } from "../app/streamManager";
import { Composer } from "./Composer";
import { TurnTimeline } from "./TurnTimeline";

interface Props {
  session: SessionSummary | null;
  onOpenSessions: () => void;
}

const ACTIVE = new Set(["pending", "processing", "finalizing"]);

export function ChatView({ session, onOpenSessions }: Props) {
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

  const header = (
    <Stack component="header" direction="row" spacing={1} sx={{ alignItems: "center", minHeight: 64, px: { xs: 1.5, sm: 3 }, borderBottom: "1px solid", borderColor: "divider", bgcolor: "background.paper" }}>
      <IconButton aria-label="打开会话列表" onClick={onOpenSessions} sx={{ display: { md: "none" } }}><MenuRounded /></IconButton>
      <Typography variant="subtitle1" sx={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 700 }}>
        {session?.title?.trim() || "新对话"}
      </Typography>
    </Stack>
  );

  if (session === null) {
    return <Box sx={{ minHeight: "100dvh" }}>{header}<EmptyState title="创建一个新对话" detail="从左侧的新对话开始与 Amadeus 交流。" /></Box>;
  }

  const draft = drafts[session.sessionId] ?? "";
  return (
    <Box sx={{ display: "grid", minHeight: "100dvh", gridTemplateRows: "auto minmax(0, 1fr) auto" }}>
      {header}
      <TurnTimeline
        key={session.sessionId}
        sessionId={session.sessionId}
        rows={rows}
        pending={turns.isPending}
        failed={turns.isError}
      />
      <Composer
        value={draft}
        busy={createTurn.isPending}
        activeTurn={activeTurn}
        cancelling={cancelTurn.isPending}
        onChange={(value) => setDrafts((current) => ({ ...current, [session.sessionId]: value }))}
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
