import ContentCopyRounded from "@mui/icons-material/ContentCopyRounded";
import { useState, type ReactNode } from "react";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Snackbar from "@mui/material/Snackbar";
import Tooltip from "@mui/material/Tooltip";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownMessage({ content }: { content: string }) {
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  const copyCode = async (raw: string) => {
    try {
      await navigator.clipboard.writeText(raw);
      setCopyNotice("代码已复制");
    } catch {
      setCopyNotice("复制失败，请手动选择代码");
    }
  };

  return (
    <>
      <Box sx={{ overflowWrap: "anywhere", "& p": { my: 1.25 }, "& ul, & ol": { pl: 3 }, "& blockquote": { mx: 0, pl: 2, borderLeft: "3px solid", borderColor: "divider", color: "text.secondary" }, "& table": { borderCollapse: "collapse", minWidth: 480 }, "& th, & td": { border: "1px solid", borderColor: "divider", p: 1 }, "& pre": { m: 0 } }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrlTransform}
        components={{
          a: ({ href, children }) => href
            ? <Link href={href} target="_blank" rel="noopener noreferrer">{children}</Link>
            : <Box component="span">{children}</Box>,
          table: ({ children }) => <Box sx={{ maxWidth: "100%", overflowX: "auto", my: 2 }}><table>{children}</table></Box>,
          code: ({ className, children, ...props }) => {
            const raw = codeText(children).replace(/\n$/, "");
            const block = className?.startsWith("language-") || raw.includes("\n");
            if (!block) return <Box component="code" sx={{ px: 0.5, py: 0.15, borderRadius: 0.5, bgcolor: "action.hover", fontFamily: "ui-monospace, monospace" }} {...props}>{children}</Box>;
            return (
              <Box sx={{ position: "relative", maxWidth: "100%", overflowX: "auto", my: 2, p: 2, border: "1px solid", borderColor: "divider", borderRadius: 1, bgcolor: "action.hover" }}>
                <Tooltip title="复制代码"><IconButton size="small" aria-label="复制代码" onClick={() => void copyCode(raw)} sx={{ position: "absolute", top: 4, right: 4 }}><ContentCopyRounded fontSize="small" /></IconButton></Tooltip>
                <code className={className} {...props}>{children}</code>
              </Box>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
      </Box>
      <Snackbar
        open={copyNotice !== null}
        autoHideDuration={2400}
        message={copyNotice ?? ""}
        onClose={() => setCopyNotice(null)}
      />
    </>
  );
}

function codeText(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return `${children}`;
  if (Array.isArray(children)) return children.map(codeText).join("");
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
