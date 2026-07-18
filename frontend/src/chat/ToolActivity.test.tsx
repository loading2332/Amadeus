import { render, screen } from "@testing-library/react";

import { ToolActivity } from "./ToolActivity";

describe("ToolActivity", () => {
  it("shows an active tool as an expanded process row", () => {
    const { container } = render(<ToolActivity part={{
      kind: "tool",
      id: "tool:1",
      activityId: "1",
      toolName: "lookup_fixture",
      state: "started",
      collapsed: false,
    }} />);
    expect(screen.getByText("调用中")).toBeInTheDocument();
    expect(container.firstChild).toHaveAttribute("data-collapsed", "false");
  });

  it("automatically compacts a completed tool into a summary", () => {
    const { container } = render(<ToolActivity part={{
      kind: "tool",
      id: "tool:1",
      activityId: "1",
      toolName: "lookup_fixture",
      state: "completed",
      collapsed: true,
    }} />);
    expect(screen.getByText("lookup_fixture · 已完成")).toBeInTheDocument();
    expect(container.firstChild).toHaveAttribute("data-collapsed", "true");
  });
});
