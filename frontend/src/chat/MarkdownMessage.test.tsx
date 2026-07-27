import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReactMarkdown from "react-markdown";

import { MarkdownMessage } from "./MarkdownMessage";

vi.mock("react-markdown", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-markdown")>();
  return { ...actual, default: vi.fn(actual.default) };
});

describe("MarkdownMessage", () => {
  it("renders GFM without activating raw HTML", () => {
    const { container } = render(
      <MarkdownMessage content={'- [x] 完成\n\n<script data-testid="unsafe">alert(1)</script>'} />,
    );
    expect(screen.getByText("完成")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });

  it("removes dangerous link protocols", () => {
    render(<MarkdownMessage content="[危险链接](javascript:alert(1))" />);
    expect(screen.getByText("危险链接")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "危险链接" })).toBeNull();
  });

  it("copies the original code and confirms the action", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<MarkdownMessage content={'```ts\nconst answer = 42;\n```'} />);
    await user.click(screen.getByRole("button", { name: "复制代码" }));
    expect(writeText).toHaveBeenCalledWith("const answer = 42;");
    expect(await screen.findByText("代码已复制")).toBeInTheDocument();
  });

  it("keeps rendering an unfinished streaming code fence", () => {
    const { container } = render(<MarkdownMessage content={'回答中\n```ts\nconst partial = true;'} />);
    expect(screen.getByText("回答中")).toBeInTheDocument();
    expect(container.querySelector("pre code")).toHaveTextContent("const partial = true;");
  });

  it("contains wide tables in their own horizontal scroller", () => {
    const { container } = render(<MarkdownMessage content={'| A | B |\n| - | - |\n| one | two |'} />);
    const table = container.querySelector("table");
    expect(table?.parentElement).toHaveStyle({ overflowX: "auto" });
  });

  it("contains long code in its own horizontal scroller", () => {
    const { container } = render(
      <MarkdownMessage content={`\`\`\`text\n${"long-token".repeat(40)}\n\`\`\``} />,
    );
    expect(container.querySelector("pre code")?.parentElement).toHaveStyle({ overflowX: "auto" });
  });

  it("highlights fenced code blocks with a language annotation", () => {
    const { container } = render(
      <MarkdownMessage content={'```js\nconst answer = 42;\n```'} />,
    );
    const keyword = container.querySelector("code .hljs-keyword");
    expect(keyword).not.toBeNull();
    expect(keyword).toHaveTextContent("const");
  });

  it("shows the language label on fenced code blocks", () => {
    render(<MarkdownMessage content={'```python\nprint("hi")\n```'} />);
    expect(screen.getByText("python")).toBeInTheDocument();
  });

  it("does not highlight fenced code without a language annotation", () => {
    const { container } = render(<MarkdownMessage content={'```\nconst answer = 42;\n```'} />);
    expect(container.querySelector("code [class^='hljs-']")).toBeNull();
  });

  it("heals unterminated emphasis while streaming", () => {
    const { container } = render(<MarkdownMessage content="结论是**非常重要" streaming />);
    const strong = container.querySelector("strong");
    expect(strong).toHaveTextContent("非常重要");
    expect(container.textContent).not.toContain("**");
  });

  it("renders the authoritative source untouched when not streaming", () => {
    const { container } = render(<MarkdownMessage content="结论是**非常重要" />);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toContain("**非常重要");
  });

  it("re-parses only the growing tail block during streaming", () => {
    const mocked = vi.mocked(ReactMarkdown);
    const base = "# 标题\n\n第一段固定内容。\n\n第二段";
    const { rerender } = render(<MarkdownMessage content={base} streaming />);
    expect(screen.getByText("第一段固定内容。")).toBeInTheDocument();

    mocked.mockClear();
    rerender(<MarkdownMessage content={`${base}继续增长`} streaming />);

    const rerendered = mocked.mock.calls.map(([props]) => props.children);
    expect(rerendered).toEqual(["第二段继续增长"]);
  });
});
