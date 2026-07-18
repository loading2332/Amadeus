import AddRounded from "@mui/icons-material/AddRounded";
import ChatBubbleOutlineRounded from "@mui/icons-material/ChatBubbleOutlineRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Typography from "@mui/material/Typography";

import type { SessionSummary } from "../api/contracts";
import { ThemeModeControl } from "../app/ThemeModeControl";

interface Props {
  sessions: SessionSummary[];
  selectedId: number | null;
  creating: boolean;
  onSelect: (sessionId: number) => void;
  onCreate: () => void;
}

export function SessionSidebar({ sessions, selectedId, creating, onSelect, onCreate }: Props) {
  return (
    <Box sx={{ display: "flex", height: "100dvh", flexDirection: "column", bgcolor: "#18212b", color: "#f4f7fa", borderRight: "1px solid rgba(255,255,255,0.08)" }}>
      <Typography variant="h6" sx={{ px: 2.5, pt: 2.5, pb: 1.5, fontWeight: 750, letterSpacing: "-0.02em" }}>
        Amadeus
      </Typography>
      <Button
        variant="contained"
        startIcon={creating ? <CircularProgress size={16} color="inherit" /> : <AddRounded />}
        disabled={creating}
        onClick={onCreate}
        sx={{ mx: 2, my: 1.5, minHeight: 42 }}
      >
        新对话
      </Button>
      <List component="nav" aria-label="会话列表" sx={{ flex: 1, overflowY: "auto", px: 1.25, py: 1 }}>
        {sessions.map((session) => (
          <ListItemButton
            key={session.sessionId}
            selected={session.sessionId === selectedId}
            onClick={() => onSelect(session.sessionId)}
            sx={{ mb: 0.5, borderRadius: 1, "&.Mui-selected": { bgcolor: "rgba(255,255,255,0.10)" }, "&.Mui-selected:hover": { bgcolor: "rgba(255,255,255,0.14)" } }}
          >
            <ListItemIcon sx={{ minWidth: 34, color: "inherit" }}><ChatBubbleOutlineRounded fontSize="small" /></ListItemIcon>
            <ListItemText
              primary={session.title?.trim() || "新对话"}
              slotProps={{ primary: { noWrap: true, sx: { fontSize: 14 } } }}
            />
          </ListItemButton>
        ))}
      </List>
      <Divider sx={{ borderColor: "rgba(255,255,255,0.10)" }} />
      <Box sx={{ p: 2 }}><ThemeModeControl /></Box>
    </Box>
  );
}
