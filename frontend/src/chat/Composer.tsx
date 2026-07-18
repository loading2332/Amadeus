import { useRef } from "react";
import SendRounded from "@mui/icons-material/SendRounded";
import StopRounded from "@mui/icons-material/StopRounded";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";

import type { Turn } from "../api/contracts";

interface Props {
  value: string;
  busy: boolean;
  activeTurn: Turn | null;
  cancelling: boolean;
  onChange: (value: string) => void;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function Composer({ value, busy, activeTurn, cancelling, onChange, onSend, onStop }: Props) {
  const composing = useRef(false);
  const canSend = value.trim().length > 0 && !busy && activeTurn === null;
  const submit = () => {
    const message = value.trim();
    if (message !== "" && canSend) onSend(message);
  };

  return (
    <Box sx={{ borderTop: "1px solid", borderColor: "divider", bgcolor: "background.paper", px: { xs: 1.5, sm: 3 }, pt: 1.5, pb: "max(12px, env(safe-area-inset-bottom))" }}>
      <Box sx={{ display: "flex", width: "100%", maxWidth: 900, mx: "auto", alignItems: "flex-end", gap: 1, border: "1px solid", borderColor: "divider", borderRadius: 1.5, p: 1 }}>
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
          slotProps={{ input: { sx: { p: 0.5, "& fieldset": { border: 0 } } } }}
        />
        {activeTurn !== null ? (
          <Tooltip title="停止生成"><span><IconButton aria-label="停止生成" color="error" disabled={cancelling || activeTurn.status === "finalizing"} onClick={onStop}><StopRounded /></IconButton></span></Tooltip>
        ) : (
          <Tooltip title="发送"><span><IconButton aria-label="发送消息" color="primary" disabled={!canSend} onClick={submit}><SendRounded /></IconButton></span></Tooltip>
        )}
      </Box>
    </Box>
  );
}
