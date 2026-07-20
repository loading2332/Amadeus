import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { SessionSummary } from "../api/contracts";
import { SessionSidebar } from "./SessionSidebar";

vi.mock("../app/ThemeModeControl", () => ({
  ThemeModeControl: () => <button type="button">theme</button>,
}));

const session: SessionSummary = {
  sessionId: 7,
  userId: 1,
  title: null,
  metadata: {},
  createdAt: "2026-07-19T08:00:00+08:00",
  updatedAt: "2026-07-19T08:00:00+08:00",
};

describe("SessionSidebar", () => {
  it("shows a compact retry action when creating a session fails", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(
      <SessionSidebar
        sessions={[]}
        selectedId={null}
        creating={false}
        createFailed
        onSelect={vi.fn()}
        onCreate={onCreate}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("新对话创建失败");
    await user.click(screen.getByRole("button", { name: "重试新建" }));
    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("uses a neutral fallback until the first-message title arrives", () => {
    const { rerender } = render(
      <SessionSidebar
        sessions={[session]}
        selectedId={session.sessionId}
        creating={false}
        createFailed={false}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    expect(within(screen.getByRole("navigation", { name: "会话列表" })).getByRole("button", { name: "新对话" })).toBeInTheDocument();
    expect(screen.queryByText("新对话 #7")).not.toBeInTheDocument();

    rerender(
      <SessionSidebar
        sessions={[{ ...session, title: "首条消息摘要" }]}
        selectedId={session.sessionId}
        creating={false}
        createFailed={false}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
      />,
    );
    expect(within(screen.getByRole("navigation", { name: "会话列表" })).getByRole("button", { name: "首条消息摘要" })).toBeInTheDocument();
  });
});
