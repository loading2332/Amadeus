import ContentCopyRounded from "@mui/icons-material/ContentCopyRounded";
import {
  isValidElement,
  memo,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Snackbar from "@mui/material/Snackbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { SxProps, Theme } from "@mui/material/styles";
import { marked } from "marked";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import remend from "remend";

import "./highlight.css";

interface MarkdownMessageProps {
  content: string;
  /** 流式进行中:对未闭合的 markdown 语法做自愈预处理;终态渲染权威原文。 */
  streaming?: boolean;
  /** 在最后一个文本块的行尾渲染脉冲圆点光标(仅当回答尾部正在生成文本时开启)。 */
  cursor?: boolean;
}

type CopyCode = (raw: string) => void;

export const MarkdownMessage = memo(function MarkdownMessage({
  content,
  streaming = false,
  cursor = false,
}: MarkdownMessageProps) {
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  const onCopyCode = useCallback<CopyCode>((raw) => {
    void navigator.clipboard.writeText(raw).then(
      () => setCopyNotice("代码已复制"),
      () => setCopyNotice("复制失败，请手动选择代码"),
    );
  }, []);

  const source = streaming ? remend(content) : content;
  // 按顶层 block 切分:流式期间只有尾部 block 的 raw 变化,
  // 之前的 block 字符串引用值不变 → MarkdownBlock 的 memo 直接命中,免去全量重解析。
  const blocks = useMemo(() => marked.lexer(source).map((token) => token.raw), [source]);

  return (
    <>
      <Box
        data-testid={cursor ? "streaming-cursor" : undefined}
        sx={cursor ? markdownCursorSx : markdownSx}
      >
        {blocks.map((raw, index) => (
          // 块只会在尾部增长/变化,索引 key 稳定。
          <MarkdownBlock key={index} raw={raw} onCopyCode={onCopyCode} />
        ))}
      </Box>
      <Snackbar
        open={copyNotice !== null}
        autoHideDuration={2400}
        message={copyNotice ?? ""}
        onClose={() => setCopyNotice(null)}
      />
    </>
  );
});

const MarkdownBlock = memo(function MarkdownBlock({
  raw,
  onCopyCode,
}: {
  raw: string;
  onCopyCode: CopyCode;
}) {
  const components = useMemo(() => createComponents(onCopyCode), [onCopyCode]);
  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      urlTransform={safeUrlTransform}
      components={components}
    >
      {raw}
    </ReactMarkdown>
  );
});

const remarkPlugins = [remarkGfm];
const rehypePlugins = [[rehypeHighlight, { detect: false }]] satisfies Parameters<
  typeof ReactMarkdown
>[0]["rehypePlugins"];

function createComponents(onCopyCode: CopyCode): Components {
  return {
    a: ({ href, children }) => href
      ? <Link href={href} target="_blank" rel="noopener noreferrer">{children}</Link>
      : <Box component="span">{children}</Box>,
    table: ({ children }) => <Box sx={{ maxWidth: "100%", overflowX: "auto", my: 2 }}><table>{children}</table></Box>,
    code: ({ className, children, ...props }) => {
      const raw = codeText(children).replace(/\n$/, "");
      const language = /language-([\w#+.-]+)/.exec(className ?? "")?.[1];
      const block = language !== undefined || raw.includes("\n");
      if (!block) return <Box component="code" sx={{ px: 0.5, py: 0.15, borderRadius: 0.5, bgcolor: "action.hover", fontFamily: "ui-monospace, monospace" }} {...props}>{children}</Box>;
      return (
        <Box sx={{ position: "relative", maxWidth: "100%", overflowX: "auto", my: 2, p: 2, border: "1px solid", borderColor: "divider", borderRadius: 2, bgcolor: "action.hover", fontSize: 13.5 }}>
          {language ? (
            <Typography
              component="span"
              variant="caption"
              aria-hidden
              sx={{ position: "absolute", top: 8, right: 40, color: "text.secondary", userSelect: "none" }}
            >
              {language}
            </Typography>
          ) : null}
          <Tooltip title="复制代码"><IconButton size="small" aria-label="复制代码" onClick={() => onCopyCode(raw)} sx={{ position: "absolute", top: 6, right: 6, opacity: 0.7, "&:hover": { opacity: 1 } }}><ContentCopyRounded fontSize="small" /></IconButton></Tooltip>
          <code className={className} {...props}>{children}</code>
        </Box>
      );
    },
  };
}

const markdownBaseSx = {
  overflowWrap: "anywhere",
  "& p": { my: 1.25 },
  "& ul, & ol": { pl: 3 },
  "& blockquote": {
    mx: 0,
    pl: 2,
    borderLeft: "3px solid",
    borderColor: "divider",
    color: "text.secondary",
  },
  "& h1, & h2, & h3, & h4, & h5, & h6": { mt: 3, mb: 1.5, fontWeight: 600, lineHeight: 1.4 },
  "& h1": { fontSize: "1.5rem" },
  "& h2": { fontSize: "1.25rem" },
  "& h3": { fontSize: "1.125rem" },
  "& h4": { fontSize: "1rem" },
  "& h5": { fontSize: "0.9375rem" },
  "& h6": { fontSize: "0.875rem" },
  "& img": { maxWidth: "100%", borderRadius: 1 },
  "& table": { borderCollapse: "collapse" },
  "& th, & td": { border: "1px solid", borderColor: "divider", p: 1 },
  "& th": { bgcolor: "action.hover", fontWeight: 600 },
  "& hr": { border: 0, borderTop: "1px solid", borderColor: "divider", my: 2 },
  "& li > input[type=checkbox]": { mr: 1 },
  "& pre": { m: 0 },
} as const;

const markdownSx: SxProps<Theme> = markdownBaseSx;

// 光标挂在最后一个文本叶子元素的行尾;尾块是代码块/表格时不显示
// (代码内容增长本身就是进度信号,圆点混进代码反而错误)。
const cursorDotTargets = [
  "& > :where(p, h1, h2, h3, h4, h5, h6):last-child::after",
  "& > blockquote:last-child > p:last-child::after",
  "& > :where(ul, ol):last-child li:last-child::after",
] as const;

const cursorDot = {
  content: '""',
  display: "inline-block",
  width: "0.5em",
  height: "0.5em",
  marginLeft: "0.3em",
  borderRadius: "50%",
  backgroundColor: "currentcolor",
  verticalAlign: "middle",
  animation: "amadeus-cursor-pulse 1.2s ease-in-out infinite",
} as const;

const cursorSx = {
  ...Object.fromEntries(cursorDotTargets.map((selector) => [selector, cursorDot])),
  "@keyframes amadeus-cursor-pulse": {
    "0%, 100%": { opacity: 0.9, transform: "scale(1)" },
    "50%": { opacity: 0.3, transform: "scale(0.8)" },
  },
  "@media (prefers-reduced-motion: reduce)": Object.fromEntries(
    cursorDotTargets.map((selector) => [selector, { animation: "none", opacity: 0.6 }]),
  ),
};

const markdownCursorSx: SxProps<Theme> = { ...markdownBaseSx, ...cursorSx };

function codeText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return `${children}`;
  if (Array.isArray(children)) return children.map(codeText).join("");
  if (isValidElement<{ children?: ReactNode }>(children)) return codeText(children.props.children);
  return "";
}

function safeUrlTransform(url: string): string {
  if (url.startsWith("/") || url.startsWith("#")) return url;
  try {
    const parsed = new URL(url);
    if (["http:", "https:", "mailto:"].includes(parsed.protocol)) return defaultUrlTransform(url);
  } catch {
    return "";
  }
  return "";
}
