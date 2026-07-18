import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MarkdownMessage } from "./MarkdownMessage";

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
    render(<MarkdownMessage content={'回答中\n```ts\nconst partial = true;'} />);
    expect(screen.getByText("回答中")).toBeInTheDocument();
    expect(screen.getByText("const partial = true;")).toBeInTheDocument();
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
});
