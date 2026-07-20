import { useId } from "react";
import AddRounded from "@mui/icons-material/AddRounded";
import CloseRounded from "@mui/icons-material/CloseRounded";
import MenuOpenRounded from "@mui/icons-material/MenuOpenRounded";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { SessionSummary } from "../api/contracts";
import { ThemeModeControl } from "../app/ThemeModeControl";
import { groupSessionsByDate } from "./sessionGroups";

interface Props {
  sessions: SessionSummary[];
  selectedId: number | null;
  creating: boolean;
  createFailed: boolean;
  onSelect: (sessionId: number) => void;
  onCreate: () => void;
  onClose?: () => void;
  onToggleCollapse?: () => void;
}

const navigationRowSx = {
  minHeight: 40,
  borderRadius: "8px",
  px: 1.25,
  "&:hover": { bgcolor: "action.hover" },
  "&.Mui-focusVisible": {
    outline: "2px solid",
    outlineColor: "primary.main",
    outlineOffset: "-2px",
  },
} as const;

export function SessionSidebar({
  sessions,
  selectedId,
  creating,
  createFailed,
  onSelect,
  onCreate,
  onClose,
  onToggleCollapse,
}: Props) {
  const groups = groupSessionsByDate(sessions);
  const groupIdPrefix = useId();

  return (
    <Box
      sx={{
        display: "flex",
        width: 280,
        height: "100%",
        flexDirection: "column",
        overflow: "hidden",
        bgcolor: "background.paper",
        color: "text.primary",
      }}
    >
      <Box sx={{ display: "flex", minHeight: 64, alignItems: "center", px: 2, gap: 0.5 }}>
        <Typography variant="h6" sx={{ flex: 1, fontWeight: 600 }}>
          Amadeus
        </Typography>
        {onClose ? (
          <Tooltip title="关闭会话列表">
            <IconButton aria-label="关闭会话列表" onClick={onClose}>
              <CloseRounded />
            </IconButton>
          </Tooltip>
        ) : null}
        {onToggleCollapse ? (
          <Tooltip title="收起侧边栏">
            <IconButton aria-label="收起侧边栏" onClick={onToggleCollapse}>
              <MenuOpenRounded />
            </IconButton>
          </Tooltip>
        ) : null}
      </Box>

      <Box sx={{ px: 1.25, pb: 1 }}>
        <ListItemButton
          aria-label="新对话"
          disabled={creating}
          onClick={onCreate}
          sx={navigationRowSx}
        >
          <ListItemIcon sx={{ minWidth: 36, color: "inherit" }}>
            {creating ? <CircularProgress size={19} color="inherit" /> : <AddRounded fontSize="small" />}
          </ListItemIcon>
          <ListItemText
            primary="新对话"
            slotProps={{ primary: { sx: { fontSize: 14, fontWeight: 600 } } }}
          />
        </ListItemButton>
        {createFailed ? (
          <Stack
            role="alert"
            direction="row"
            sx={{ minHeight: 32, mt: 0.5, px: 1.25, alignItems: "center" }}
          >
            <Typography variant="caption" color="error.main" sx={{ flex: 1 }}>
              新对话创建失败
            </Typography>
            <Button
              aria-label="重试新建"
              size="small"
              startIcon={<RefreshRounded fontSize="small" />}
              onClick={onCreate}
              sx={{ minWidth: 0 }}
            >
              重试
            </Button>
          </Stack>
        ) : null}
      </Box>

      <List
        component="nav"
        aria-label="会话列表"
        sx={{ flex: 1, minHeight: 0, overflowY: "auto", px: 1.25, py: 0.5 }}
      >
        {groups.map((group) => {
          const headingId = `${groupIdPrefix}-${group.key}`;
          return (
            <Box component="section" aria-labelledby={headingId} key={group.key} sx={{ mb: 1.25 }}>
              <Typography
                id={headingId}
                variant="caption"
                sx={{ display: "block", px: 1.25, pt: 1, pb: 0.5, color: "text.secondary", fontWeight: 600 }}
              >
                {group.label}
              </Typography>
              {group.sessions.map((session) => (
                <ListItemButton
                  key={session.sessionId}
                  selected={session.sessionId === selectedId}
                  onClick={() => onSelect(session.sessionId)}
                  sx={{
                    ...navigationRowSx,
                    mb: 0.25,
                    "&.Mui-selected": { bgcolor: "action.selected" },
                    "&.Mui-selected:hover": { bgcolor: "action.selected" },
                  }}
                >
                  <ListItemText
                    primary={session.title?.trim() || "新对话"}
                    slotProps={{ primary: { noWrap: true, sx: { fontSize: 14 } } }}
                  />
                </ListItemButton>
              ))}
            </Box>
          );
        })}
      </List>

      <Divider />
      <Box data-testid="sidebar-footer" sx={{ display: "flex", minHeight: 60, alignItems: "center", px: 1.25 }}>
        <ThemeModeControl />
      </Box>
    </Box>
  );
}
