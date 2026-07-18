import { lazy, Suspense } from "react";
import AutorenewRounded from "@mui/icons-material/AutorenewRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { Turn } from "../api/contracts";
import { useRetryTurnMutation } from "../api/queries";
import { turnStreamManager } from "../app/streamManager";
import { useLiveTurnStore } from "../streaming/store";
import { ToolActivity } from "./ToolActivity";

const MarkdownMessage = lazy(() =>
  import("./MarkdownMessage").then((module) => ({ default: module.MarkdownMessage })),
);

export function TurnItem({ turn }: { turn: Turn }) {
  const live = useLiveTurnStore((state) => state.turns[turn.turnId]);
  const retry = useRetryTurnMutation();
  const parts = live?.parts ?? [];
  const fallback = turn.status === "done" ? turn.answer : turn.partialAnswer;
  const status = live?.status ?? turn.status;
  const error = live?.error ?? turn.error;

  return (
    <Box component="article" sx={{ contentVisibility: "auto", containIntrinsicSize: "auto 320px" }}>
      <Box sx={{ ml: { xs: 2, sm: 8 }, mb: 3, pl: 2, borderLeft: "2px solid", borderColor: "primary.main" }}>
        <Typography variant="caption" color="text.secondary">你</Typography>
        <Typography sx={{ whiteSpace: "pre-wrap" }}>{turn.content}</Typography>
      </Box>
      <Box>
        <Typography variant="caption" sx={{ display: "block", mb: 1.5, color: "primary.main", fontWeight: 700 }}>Amadeus</Typography>
        {parts.length > 0 ? parts.map((part) =>
          part.kind === "text" ? <Suspense key={part.id} fallback={<Typography sx={{ whiteSpace: "pre-wrap" }}>{part.content}</Typography>}><MarkdownMessage content={part.content} /></Suspense> : <ToolActivity key={part.id} part={part} />,
        ) : fallback ? <Suspense fallback={<Typography sx={{ whiteSpace: "pre-wrap" }}>{fallback}</Typography>}><MarkdownMessage content={fallback} /></Suspense> : <PendingState status={status} />}
        {live?.streamError ? (
          <Typography role="alert" color="error.main" variant="body2" sx={{ mt: 2 }}>
            {live.streamError}
          </Typography>
        ) : null}
        {status === "failed" || status === "cancelled" ? (
          <Stack spacing={1} sx={{ mt: 2, alignItems: "flex-start" }}>
            <Typography color={status === "failed" ? "error.main" : "text.secondary"} variant="body2">
              {status === "failed" ? (error?.message ?? "回答失败，已保留部分内容。") : "已停止生成；停止前完成的工具操作不会撤销。"}
            </Typography>
            {(status === "cancelled" || error?.retryable) ? (
              <Button
                size="small"
                startIcon={<AutorenewRounded />}
                disabled={retry.isPending}
                onClick={() => retry.mutate(turn.turnId, { onSuccess: (next) => turnStreamManager.connect(next.turnId, next.sessionId) })}
              >
                重试
              </Button>
            ) : null}
          </Stack>
        ) : null}
      </Box>
    </Box>
  );
}

function PendingState({ status }: { status: Turn["status"] }) {
  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: "center", color: "text.secondary" }}>
      <CircularProgress size={16} /><Typography variant="body2">{status === "pending" ? "等待处理" : "正在回答"}</Typography>
    </Stack>
  );
}
