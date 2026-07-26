import { useRef } from "react";
import RefreshRounded from "@mui/icons-material/RefreshRounded";
import SendRounded from "@mui/icons-material/SendRounded";
import StopRounded from "@mui/icons-material/StopRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { Turn } from "../api/contracts";

interface Props {
  value: string;
  busy: boolean;
  activeTurn: Turn | null;
  cancelling: boolean;
  sendFailed: boolean;
  onChange: (value: string) => void;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function Composer({ value, busy, activeTurn, cancelling, sendFailed, onChange, onSend, onStop }: Props) {
  const composing = useRef(false);
  const canSend = value.trim().length > 0 && !busy && activeTurn === null;
  const submit = () => {
    const message = value.trim();
    if (message !== "" && canSend) onSend(message);
  };

  return (
    <Box data-testid="composer-bar" sx={{ px: { xs: 1.5, sm: 3 }, pt: 1, pb: "max(24px, calc(env(safe-area-inset-bottom) + 8px))" }}>
      <Box
        data-testid="composer-shell"
        sx={(theme) => ({
          display: "flex",
          width: "100%",
          maxWidth: 900,
          mx: "auto",
          alignItems: "flex-end",
          gap: 1,
          border: "1px solid",
          borderColor: "divider",
          // 固定圆角:单行时接近药丸,多行时保持圆角矩形。
          // 不用 999——胶囊圆角在多行高度下两端成大半圆,顶/底行文字会伸出弧线。
          borderRadius: "28px",
          bgcolor: "background.paper",
          boxShadow:
            "0 1px 3px rgba(0,0,0,0.07), 0 10px 28px rgba(0,0,0,0.09)",
          p: 1,
          transition: theme.transitions.create(["border-color", "box-shadow"], { duration: theme.transitions.duration.shortest }),
          "&:focus-within": {
            borderColor: "primary.main",
            outline: "2px solid var(--mui-palette-primary-main)",
            outlineOffset: "-2px",
            boxShadow:
              "0 1px 3px rgba(0,0,0,0.08), 0 10px 28px rgba(var(--mui-palette-primary-mainChannel) / 0.18)",
            ...theme.applyStyles("dark", {
              boxShadow: "none",
            }),
          },
        })}
      >
        <TextField
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onCompositionStart={() => { composing.current = true; }}
          onCompositionEnd={() => { composing.current = false; }}
          onKeyDown={(event) => {
            const mobile = window.matchMedia("(max-width: 600px)").matches;
            if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && !mobile) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="给 Amadeus 发消息"
          multiline
          minRows={1}
          maxRows={8}
          fullWidth
          disabled={busy}
          slotProps={{ input: { sx: { minHeight: 40, py: 0.5, pr: 0.5, pl: 1.5, "&& .MuiOutlinedInput-notchedOutline": { border: 0 } } } }}
        />
        {activeTurn !== null ? (
          <Tooltip title="停止生成"><span><IconButton aria-label="停止生成" disabled={cancelling || activeTurn.status === "finalizing"} onClick={onStop} sx={{ width: 40, height: 40, bgcolor: "text.primary", color: "background.paper", transition: "transform 120ms ease, opacity 120ms ease", "&:hover": { bgcolor: "text.primary", opacity: 0.86 }, "&:active": { transform: "scale(0.94)" }, "&.Mui-disabled": { bgcolor: "action.disabledBackground" } }}><StopRounded fontSize="small" /></IconButton></span></Tooltip>
        ) : (
          <Tooltip title="发送"><span><IconButton aria-label="发送消息" disabled={!canSend} onClick={submit} sx={{ width: 40, height: 40, bgcolor: "primary.main", color: "primary.contrastText", transition: "transform 120ms ease, background-color 120ms ease, opacity 120ms ease", "&:hover": { bgcolor: "primary.main", opacity: 0.9 }, "&:active": { transform: "scale(0.94)" }, "&.Mui-disabled": { bgcolor: "action.disabledBackground", color: "action.disabled" } }}><SendRounded fontSize="small" /></IconButton></span></Tooltip>
        )}
      </Box>
      {sendFailed ? (
        <Stack
          role="alert"
          direction="row"
          sx={{ width: "100%", maxWidth: 900, minHeight: 32, mx: "auto", mt: 0.5, px: 1.5, alignItems: "center" }}
        >
          <Typography variant="caption" color="error.main" sx={{ flex: 1 }}>
            消息未发送，请检查连接后重试。
          </Typography>
          <Button
            aria-label="重试发送"
            size="small"
            startIcon={<RefreshRounded fontSize="small" />}
            disabled={!canSend}
            onClick={submit}
            sx={{ minWidth: 0 }}
          >
            重试
          </Button>
        </Stack>
      ) : null}
    </Box>
  );
}
