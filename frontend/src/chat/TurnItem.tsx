import { lazy, memo, Suspense, useState } from "react";
import AutorenewRounded from "@mui/icons-material/AutorenewRounded";
import ContentCopyRounded from "@mui/icons-material/ContentCopyRounded";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import type { Turn } from "../api/contracts";
import { useRetryTurnMutation } from "../api/queries";
import { turnStreamManager } from "../app/streamManager";
import type { StreamPart } from "../streaming/reducer";
import { useLiveTurnStore } from "../streaming/store";
import { useSmoothText } from "../streaming/useSmoothText";
import { fadeUpProps, motion } from "../ui/motion";
import { ToolActivity } from "./ToolActivity";

const MarkdownMessage = lazy(() =>
  import("./MarkdownMessage").then((module) => ({
    default: module.MarkdownMessage,
  })),
);

export const TurnItem = memo(function TurnItem({ turn }: { turn: Turn }) {
  const live = useLiveTurnStore((state) => state.turns[turn.turnId]);
  const retry = useRetryTurnMutation();
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const parts = live?.parts ?? [];
  const fallback = turn.status === "done" ? turn.answer : turn.partialAnswer;
  const status = live?.status ?? turn.status;
  const error = live?.error ?? turn.error;
  const streaming = isActive(status);
  const answerSource =
    parts.length > 0
      ? parts
          .flatMap((part) => (part.kind === "text" ? [part.content] : []))
          .join("\n\n")
      : (fallback ?? "");
  const showCopyAnswer = !streaming && answerSource.trim() !== "";

  const copyAnswer = () => {
    void navigator.clipboard.writeText(answerSource).then(
      () => setCopyNotice("回答已复制"),
      () => setCopyNotice("复制失败，请手动选择内容"),
    );
  };

  return (
    <Box
      component="article"
      aria-label="一轮对话"
      sx={{ contentVisibility: "auto", containIntrinsicSize: "auto 320px" }}
    >
      <motion.div {...fadeUpProps()}>
      <Box
        aria-label="你的消息"
        sx={{
          width: "fit-content",
          maxWidth: { xs: "88%", sm: "75%" },
          ml: "auto",
          mb: { xs: 3, sm: 4, md: 2 },
          px: 2,
          py: 1.25,
          borderRadius: "18px 18px 4px 18px",
          bgcolor: "primary.main",
          color: "primary.contrastText",
        }}
      >
        <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {turn.content}
        </Typography>
      </Box>
      <Box
        aria-label="Amadeus 的回答"
        sx={{
          maxWidth: 760,
          "&:hover .amadeus-answer-actions, &:focus-within .amadeus-answer-actions": {
            opacity: 1,
          },
        }}
      >
        {parts.length > 0 ? (
          <>
            {parts.map((part) =>
              part.kind === "text" ? (
                streaming && part.id === lastTextPartId(parts) ? (
                  <SmoothTextPart
                    key={part.id}
                    content={part.content}
                    cursor={parts[parts.length - 1]?.kind === "text"}
                  />
                ) : (
                  <Suspense
                    key={part.id}
                    fallback={
                      <Typography sx={{ whiteSpace: "pre-wrap" }}>
                        {part.content}
                      </Typography>
                    }
                  >
                    <MarkdownMessage content={part.content} streaming={streaming} />
                  </Suspense>
                )
              ) : (
                <ToolActivity key={part.id} part={part} />
              ),
            )}
          </>
        ) : fallback ? (
          <Suspense
            fallback={
              <Typography sx={{ whiteSpace: "pre-wrap" }}>
                {fallback}
              </Typography>
            }
          >
            <MarkdownMessage content={fallback} />
          </Suspense>
        ) : isActive(status) ? (
          <PendingState status={status} />
        ) : status === "done" ? (
          <Typography color="text.secondary" variant="body2">
            回答已完成，但没有返回内容。
          </Typography>
        ) : null}
        {live?.streamError ? (
          <Typography
            role="alert"
            color="error.main"
            variant="body2"
            sx={{ mt: 2 }}
          >
            {live.streamError}
          </Typography>
        ) : null}
        {status === "failed" || status === "cancelled" ? (
          <Stack spacing={1} sx={{ mt: 2, alignItems: "flex-start" }}>
            <Typography
              color={status === "failed" ? "error.main" : "text.secondary"}
              variant="body2"
            >
              {status === "failed"
                ? (error?.message ?? "回答失败，已保留部分内容。")
                : "已停止生成"}
            </Typography>
            {status === "cancelled" || error?.retryable ? (
              <Button
                size="small"
                startIcon={<AutorenewRounded />}
                disabled={retry.isPending}
                onClick={() =>
                  retry.mutate(turn.turnId, {
                    onSuccess: (next) =>
                      turnStreamManager.connect(next.turnId, next.sessionId),
                  })
                }
              >
                重试
              </Button>
            ) : null}
          </Stack>
        ) : null}
        {showCopyAnswer ? (
          <Box
            className="amadeus-answer-actions"
            sx={{
              mt: 1,
              opacity: 0,
              transition: "opacity 120ms ease",
              "@media (hover: none)": { opacity: 1 },
            }}
          >
            <Tooltip title="复制全文">
              <IconButton
                size="small"
                aria-label="复制全文"
                onClick={copyAnswer}
                sx={{ color: "text.secondary" }}
              >
                <ContentCopyRounded fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        ) : null}
      </Box>
      </motion.div>
      <Snackbar
        open={copyNotice !== null}
        autoHideDuration={2400}
        message={copyNotice ?? ""}
        onClose={() => setCopyNotice(null)}
      />
    </Box>
  );
});

/** 活跃 turn 的最后一个 text part:经 useSmoothText 匀速追进显示。 */
function SmoothTextPart({ content, cursor }: { content: string; cursor: boolean }) {
  const { text } = useSmoothText(content, false);
  return (
    <Suspense
      fallback={<Typography sx={{ whiteSpace: "pre-wrap" }}>{text}</Typography>}
    >
      <MarkdownMessage content={text} streaming cursor={cursor} />
    </Suspense>
  );
}

function lastTextPartId(parts: StreamPart[]): string | null {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part?.kind === "text") return part.id;
  }
  return null;
}

function PendingState({ status }: { status: Turn["status"] }) {
  return (
    <Stack
      direction="row"
      spacing={1.25}
      sx={{ alignItems: "center", color: "text.secondary" }}
    >
      <Box
        aria-hidden
        sx={{
          display: "flex",
          gap: 0.5,
          "& span": {
            width: 6,
            height: 6,
            borderRadius: "50%",
            bgcolor: "primary.main",
            animation: "amadeus-thinking 1.2s ease-in-out infinite",
          },
          "& span:nth-of-type(2)": { animationDelay: "0.15s" },
          "& span:nth-of-type(3)": { animationDelay: "0.3s" },
          "@keyframes amadeus-thinking": {
            "0%, 80%, 100%": { opacity: 0.25, transform: "scale(0.75)" },
            "40%": { opacity: 1, transform: "scale(1)" },
          },
          "@media (prefers-reduced-motion: reduce)": {
            "& span": { animation: "none", opacity: 0.6 },
          },
        }}
      >
        <span />
        <span />
        <span />
      </Box>
      <Typography variant="body2">
        {status === "pending" ? "等待处理" : "正在回答"}
      </Typography>
    </Stack>
  );
}

function isActive(status: Turn["status"]): boolean {
  return (
    status === "pending" || status === "processing" || status === "finalizing"
  );
}
