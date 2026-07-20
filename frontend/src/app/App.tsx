import { useEffect, useMemo, useState } from "react";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Drawer from "@mui/material/Drawer";
import Typography from "@mui/material/Typography";

import { useBootstrapQuery, useCreateSessionMutation, useSessionsQuery } from "../api/queries";
import { ChatView } from "../chat/ChatView";
import { SessionSidebar } from "../sessions/SessionSidebar";
import { syncOwnerIdentity } from "./ownerIdentity";
import { readSidebarCollapsed, writeSidebarCollapsed } from "./sidebarPreference";

const SIDEBAR_WIDTH = 280;

export function App() {
  const bootstrap = useBootstrapQuery();
  const sessions = useSessionsQuery();
  const createSession = useCreateSessionMutation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopCollapsed, setDesktopCollapsed] = useState(readSidebarCollapsed);
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
    const retrying = bootstrap.isFetching || sessions.isFetching;
    return (
      <CenteredStatus>
        <Typography variant="h6">无法连接 Amadeus</Typography>
        <Typography color="text.secondary">请确认服务已启动，然后重新连接。</Typography>
        <Button
          startIcon={retrying ? <CircularProgress size={16} color="inherit" /> : <RefreshRounded />}
          disabled={retrying}
          onClick={() => {
            void bootstrap.refetch();
            void sessions.refetch();
          }}
        >
          {retrying ? "正在重试" : "重试连接"}
        </Button>
      </CenteredStatus>
    );
  }

  const selectSession = (sessionId: number) => {
    createSession.reset();
    setSelectedId(sessionId);
    setMobileOpen(false);
  };
  const createNewSession = () => {
    createSession.mutate(undefined, {
      onSuccess: (session) => {
        setSelectedId(session.sessionId);
        setMobileOpen(false);
      },
    });
  };
  const toggleDesktopSidebar = () => {
    setDesktopCollapsed((collapsed) => {
      const next = !collapsed;
      writeSidebarCollapsed(next);
      return next;
    });
  };

  return (
    <Box sx={{ display: "flex", height: "100dvh", overflow: "hidden", bgcolor: "background.default" }}>
      <Box
        data-testid="desktop-sidebar-shell"
        sx={{
          display: { xs: "none", md: "block" },
          width: desktopCollapsed ? 0 : SIDEBAR_WIDTH,
          height: "100%",
          flexShrink: 0,
          overflow: "hidden",
          opacity: desktopCollapsed ? 0 : 1,
          pointerEvents: desktopCollapsed ? "none" : "auto",
          transition: (theme) => theme.transitions.create(["width", "opacity"], {
            duration: 200,
            easing: theme.transitions.easing.easeInOut,
          }),
          "@media (prefers-reduced-motion: reduce)": { transition: "none" },
        }}
        aria-hidden={desktopCollapsed}
        inert={desktopCollapsed}
      >
        <SessionSidebar
          sessions={sessionRows}
          selectedId={effectiveSelectedId}
          creating={createSession.isPending}
          createFailed={createSession.isError}
          onSelect={selectSession}
          onCreate={createNewSession}
          onToggleCollapse={toggleDesktopSidebar}
        />
      </Box>
      <Drawer
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{ display: { xs: "block", md: "none" }, "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH } }}
      >
        <SessionSidebar sessions={sessionRows} selectedId={effectiveSelectedId} creating={createSession.isPending} createFailed={createSession.isError} onSelect={selectSession} onCreate={createNewSession} onClose={() => setMobileOpen(false)} />
      </Drawer>
      <Box component="main" sx={{ minWidth: 0, minHeight: 0, height: "100%", flex: 1, overflow: "hidden" }}>
        <ChatView
          session={sessionRows.find((item) => item.sessionId === effectiveSelectedId) ?? null}
          desktopSidebarCollapsed={desktopCollapsed}
          creatingSession={createSession.isPending}
          createSessionFailed={createSession.isError}
          onOpenSessions={() => setMobileOpen(true)}
          onOpenDesktopSidebar={toggleDesktopSidebar}
          onCreateSession={createNewSession}
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
