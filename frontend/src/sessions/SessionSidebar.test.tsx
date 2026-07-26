import { render, screen, waitFor, within } from "@testing-library/react";
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
        onDelete={vi.fn()}
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
        onDelete={vi.fn()}
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
        onDelete={vi.fn()}
      />,
    );
    expect(within(screen.getByRole("navigation", { name: "会话列表" })).getByRole("button", { name: "首条消息摘要" })).toBeInTheDocument();
  });

  it("deletes a session only after the dialog is confirmed", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <SessionSidebar
        sessions={[session]}
        selectedId={session.sessionId}
        creating={false}
        createFailed={false}
        onSelect={onSelect}
        onCreate={vi.fn()}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: "删除会话 新对话" }));

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent("删除会话？");
    await user.click(screen.getByRole("button", { name: "删除" }));

    expect(onDelete).toHaveBeenCalledOnce();
    expect(onDelete).toHaveBeenCalledWith(7);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("cancels the dialog without deleting anything", async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <SessionSidebar
        sessions={[session]}
        selectedId={session.sessionId}
        creating={false}
        createFailed={false}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: "删除会话 新对话" }));
    await user.click(screen.getByRole("button", { name: "取消" }));

    expect(onDelete).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog open with an error message and allows retrying after a failure", async () => {
    const user = userEvent.setup();
    const onDelete = vi
      .fn()
      .mockRejectedValueOnce(new Error("无法连接服务器，请检查网络后重试"))
      .mockResolvedValueOnce(undefined);
    render(
      <SessionSidebar
        sessions={[session]}
        selectedId={session.sessionId}
        creating={false}
        createFailed={false}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole("button", { name: "删除会话 新对话" }));
    await user.click(screen.getByRole("button", { name: "删除" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接服务器，请检查网络后重试");
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "删除" }));

    expect(onDelete).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
