import { handOffTerminalTurn } from "./streamManager";

describe("handOffTerminalTurn", () => {
  it("keeps the live overlay until the authoritative snapshot refreshes", async () => {
    let finishRefresh: (() => void) | undefined;
    const refresh = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishRefresh = resolve;
        }),
    );
    const remove = vi.fn();

    const handoff = handOffTerminalTurn(refresh, remove);
    expect(refresh).toHaveBeenCalledOnce();
    expect(remove).not.toHaveBeenCalled();

    finishRefresh?.();
    await handoff;
    expect(remove).toHaveBeenCalledOnce();
  });

  it("keeps the live overlay when the authoritative refresh fails", async () => {
    const remove = vi.fn();

    await expect(
      handOffTerminalTurn(() => Promise.reject(new Error("offline")), remove),
    ).rejects.toThrow("offline");
    expect(remove).not.toHaveBeenCalled();
  });
});
