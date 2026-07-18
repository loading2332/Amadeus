import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TurnTimeline } from "./TurnTimeline";

describe("TurnTimeline", () => {
  it("stops following after an upward scroll and lets the user return", async () => {
    const user = userEvent.setup();
    render(<TurnTimeline sessionId={1} rows={[]} pending={false} failed={false} />);
    const viewport = screen.getByTestId("chat-timeline");
    const scrollTo = vi.fn();
    Object.defineProperties(viewport, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 200 },
      scrollTop: { configurable: true, writable: true, value: 100 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    fireEvent.scroll(viewport);
    await user.click(screen.getByRole("button", { name: "回到底部" }));

    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1000, behavior: "smooth" });
    expect(screen.queryByRole("button", { name: "回到底部" })).not.toBeInTheDocument();
  });
});
