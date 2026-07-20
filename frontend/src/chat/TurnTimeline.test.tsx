import type { ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TurnTimeline } from "./TurnTimeline";

describe("TurnTimeline", () => {
  const baseProps: ComponentProps<typeof TurnTimeline> = {
    sessionId: 1,
    rows: [],
    pending: false,
    failed: false,
    retrying: false,
    onRetry: vi.fn(),
    desktopSidebarCollapsed: false,
    submittingFirstTurn: false,
  };

  it("centers the welcome state and hides it while the first turn is submitted", () => {
    const { rerender } = render(<TurnTimeline {...baseProps} />);

    expect(screen.getByTestId("timeline-state")).toHaveStyle({ display: "grid", placeItems: "center" });
    expect(screen.getByText("有什么想一起完成的？")).toBeInTheDocument();

    rerender(<TurnTimeline {...baseProps} submittingFirstTurn />);

    expect(screen.queryByText("有什么想一起完成的？")).not.toBeInTheDocument();
  });

  it("stops following after an upward scroll and lets the user return", async () => {
    const user = userEvent.setup();
    render(<TurnTimeline {...baseProps} />);
    const viewport = screen.getByTestId("chat-timeline");
    const scrollTo = vi.fn();
    Object.defineProperties(viewport, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 200 },
      scrollTop: { configurable: true, writable: true, value: 100 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    fireEvent.scroll(viewport);
    const returnButton = await screen.findByRole("button", { name: "回到底部" });
    expect(returnButton).toHaveTextContent("");
    expect(returnButton).toHaveStyle({ width: "40px", height: "40px" });
    fireEvent.mouseDown(returnButton);
    expect(returnButton.querySelector(".MuiTouchRipple-root")).toBeNull();
    fireEvent.mouseUp(returnButton);
    await user.click(returnButton);

    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    viewport.scrollTop = 750;
    fireEvent.scroll(viewport);
    expect(screen.getByRole("button", { name: "回到底部" })).toBeInTheDocument();

    viewport.scrollTop = 800;
    fireEvent.scroll(viewport);
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });

  it("retries loading the selected conversation in place", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<TurnTimeline {...baseProps} failed onRetry={onRetry} />);

    expect(screen.getByText("无法载入对话")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新载入" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
