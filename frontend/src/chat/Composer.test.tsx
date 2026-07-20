import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Composer } from "./Composer";

const base = {
  value: "",
  busy: false,
  activeTurn: null,
  cancelling: false,
  sendFailed: false,
  onChange: vi.fn(),
  onSend: vi.fn(),
  onStop: vi.fn(),
};

describe("Composer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(window.matchMedia).mockReturnValue({ matches: false } as MediaQueryList);
  });

  it("blocks blank messages", () => {
    render(<Composer {...base} value="   " />);
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
  });

  it("sends trimmed text from the explicit button", async () => {
    const user = userEvent.setup();
    render(<Composer {...base} value="  你好  " />);
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(base.onSend).toHaveBeenCalledWith("你好");
  });

  it("uses a stop action while the session has an active turn", () => {
    render(
      <Composer
        {...base}
        activeTurn={{
          turnId: "turn-1",
          userId: 1,
          sessionId: 1,
          content: "hi",
          status: "processing",
          answer: null,
          partialAnswer: "",
          streamVersion: 0,
          retryOfTurnId: null,
          error: null,
          metadata: {},
          createdAt: null,
          updatedAt: null,
          startedAt: null,
          finishedAt: null,
        }}
      />,
    );
    expect(screen.getByRole("button", { name: "停止生成" })).toBeEnabled();
  });

  it("sends on desktop Enter but keeps Shift+Enter as a newline", () => {
    render(<Composer {...base} value=" 你好 " />);
    const input = screen.getByPlaceholderText("给 Amadeus 发消息");
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(base.onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(base.onSend).toHaveBeenCalledWith("你好");
  });

  it("does not send while the Chinese IME is composing", () => {
    render(<Composer {...base} value="你好" />);
    const input = screen.getByPlaceholderText("给 Amadeus 发消息");
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(base.onSend).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
  });

  it("keeps mobile Enter for soft-keyboard newlines", () => {
    vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList);
    render(<Composer {...base} value="你好" />);
    fireEvent.keyDown(screen.getByPlaceholderText("给 Amadeus 发消息"), { key: "Enter" });
    expect(base.onSend).not.toHaveBeenCalled();
  });

  it("blocks duplicate submit while the request is pending", () => {
    render(<Composer {...base} value="你好" busy />);
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
  });

  it("keeps the draft visible and retries a failed send", async () => {
    const user = userEvent.setup();
    render(<Composer {...base} value="保留这条草稿" sendFailed />);

    expect(screen.getByPlaceholderText("给 Amadeus 发消息")).toHaveValue("保留这条草稿");
    expect(screen.getByRole("alert")).toHaveTextContent("消息未发送");
    await user.click(screen.getByRole("button", { name: "重试发送" }));
    expect(base.onSend).toHaveBeenCalledWith("保留这条草稿");
  });
});
