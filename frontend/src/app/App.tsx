import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Drawer from "@mui/material/Drawer";
import Typography from "@mui/material/Typography";

import { useBootstrapQuery, useCreateSessionMutation, useSessionsQuery } from "../api/queries";
import { ChatView } from "../chat/ChatView";
import { SessionSidebar } from "../sessions/SessionSidebar";
import { syncOwnerIdentity } from "./ownerIdentity";

const SIDEBAR_WIDTH = 280;

export function App() {
  const bootstrap = useBootstrapQuery();
  const sessions = useSessionsQuery();
  const createSession = useCreateSessionMutation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(() => sessionFromUrl());
  const sessionRows = useMemo(() => sessions.data ?? [], [sessions.data]);
  const effectiveSelectedId = sessionRows.some((session) => session.sessionId === selectedId)
    ? selectedId
    : (sessionRows[0]?.sessionId ?? null);

  useEffect(() => {
    if (bootstrap.data === undefined || !syncOwnerIdentity(bootstrap.data.ownerUserId)) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("session");
    window.history.replaceState(null, "", url);
  }, [bootstrap.data]);

  useEffect(() => {
    if (effectiveSelectedId === null) return;
    const url = new URL(window.location.href);
    url.searchParams.set("session", String(effectiveSelectedId));
    window.history.replaceState(null, "", url);
  }, [effectiveSelectedId]);

  if (bootstrap.isPending || sessions.isPending) {
    return <CenteredStatus><CircularProgress size={28} /><Typography>正在载入 Amadeus…</Typography></CenteredStatus>;
  }
  if (bootstrap.isError || sessions.isError) {
    return <CenteredStatus><Typography variant="h6">无法连接 Amadeus</Typography><Typography color="text.secondary">请确认 FastAPI 已启动后刷新页面。</Typography></CenteredStatus>;
  }

  const sidebar = (
    <SessionSidebar
      sessions={sessionRows}
      selectedId={effectiveSelectedId}
      creating={createSession.isPending}
      onSelect={(sessionId) => {
        setSelectedId(sessionId);
        setMobileOpen(false);
      }}
      onCreate={() => {
        createSession.mutate(undefined, {
          onSuccess: (session) => {
            setSelectedId(session.sessionId);
            setMobileOpen(false);
          },
        });
      }}
    />
  );

  return (
    <Box sx={{ display: "flex", minHeight: "100dvh", bgcolor: "background.default" }}>
      <Box sx={{ display: { xs: "none", md: "block" }, width: SIDEBAR_WIDTH, flexShrink: 0 }}>
        {sidebar}
      </Box>
      <Drawer
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{ display: { xs: "block", md: "none" }, "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH } }}
      >
        {sidebar}
      </Drawer>
      <Box component="main" sx={{ minWidth: 0, flex: 1 }}>
        <ChatView
          session={sessionRows.find((item) => item.sessionId === effectiveSelectedId) ?? null}
          onOpenSessions={() => setMobileOpen(true)}
        />
      </Box>
    </Box>
  );
}

function CenteredStatus({ children }: { children: React.ReactNode }) {
  return (
    <Box sx={{ minHeight: "100dvh", display: "grid", placeContent: "center", justifyItems: "center", gap: 2, p: 3, textAlign: "center" }}>
      {children}
    </Box>
  );
}

function sessionFromUrl(): number | null {
  const raw = new URLSearchParams(window.location.search).get("session");
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
