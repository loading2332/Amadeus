import BuildOutlined from "@mui/icons-material/BuildOutlined";
import CheckCircleOutlineRounded from "@mui/icons-material/CheckCircleOutlineRounded";
import ErrorOutlineRounded from "@mui/icons-material/ErrorOutlineRounded";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { ToolPart } from "../streaming/reducer";

export function ToolActivity({ part }: { part: ToolPart }) {
  const state = {
    started: { label: "调用中", icon: <CircularProgress size={15} /> },
    completed: { label: "已完成", icon: <CheckCircleOutlineRounded fontSize="small" /> },
    failed: { label: "调用失败", icon: <ErrorOutlineRounded fontSize="small" /> },
  }[part.state];
  if (part.collapsed) {
    return (
      <Stack
        direction="row"
        spacing={0.75}
        data-collapsed="true"
        sx={{ alignItems: "center", my: 0.75, minWidth: 0, color: "text.secondary" }}
      >
        {state.icon}
        <Typography variant="caption" sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {part.toolName} · {state.label}
        </Typography>
      </Stack>
    );
  }
  return (
    <Stack direction="row" spacing={1} data-collapsed="false" sx={{ alignItems: "center", my: 2, py: 0.75, minWidth: 0, color: "text.secondary" }}>
      <BuildOutlined fontSize="small" />
      <Typography variant="body2" sx={{ minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", fontFamily: "monospace" }}>{part.toolName}</Typography>
      {state.icon}<Typography variant="caption">{state.label}</Typography>
    </Stack>
  );
}
