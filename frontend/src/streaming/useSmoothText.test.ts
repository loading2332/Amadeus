import { act, renderHook } from "@testing-library/react";

import { useSmoothText } from "./useSmoothText";

const reducedMotion = vi.hoisted(() => ({ value: false }));

vi.mock("motion/react", () => ({
  useReducedMotion: () => reducedMotion.value,
}));

describe("useSmoothText", () => {
  let frameQueue: Map<number, FrameRequestCallback>;
  let nextHandle: number;

  beforeEach(() => {
    reducedMotion.value = false;
    frameQueue = new Map();
    nextHandle = 1;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      const handle = nextHandle;
      nextHandle += 1;
      frameQueue.set(handle, callback);
      return handle;
    });
    vi.stubGlobal("cancelAnimationFrame", (handle: number) => {
      frameQueue.delete(handle);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function runFrame() {
    const callbacks = [...frameQueue.values()];
    frameQueue.clear();
    act(() => {
      for (const callback of callbacks) callback(0);
    });
  }

  it("advances toward the target at an adaptive pace until settled", () => {
    const target = "字".repeat(100);
    const { result } = renderHook(() => useSmoothText(target, false));
    expect(result.current.text).toBe("");
    expect(result.current.settled).toBe(false);

    runFrame();
    const afterFirst = result.current.text.length;
    expect(afterFirst).toBeGreaterThan(0);
    expect(afterFirst).toBeLessThan(target.length);

    let previous = afterFirst;
    for (let index = 0; index < 100 && !result.current.settled; index += 1) {
      runFrame();
      expect(result.current.text.length).toBeGreaterThanOrEqual(previous);
      expect(target.startsWith(result.current.text)).toBe(true);
      previous = result.current.text.length;
    }
    expect(result.current.settled).toBe(true);
    expect(result.current.text).toBe(target);
    expect(frameQueue.size).toBe(0);
  });

  it("catches up instantly when the turn is done", () => {
    const target = "完整回答内容";
    const { result } = renderHook(() => useSmoothText(target, true));
    expect(result.current).toEqual({ text: target, settled: true });
    expect(frameQueue.size).toBe(0);
  });

  it("flushes the remaining buffer once done arrives mid-stream", () => {
    const target = "字".repeat(200);
    const { result, rerender } = renderHook(
      ({ done }: { done: boolean }) => useSmoothText(target, done),
      { initialProps: { done: false } },
    );
    runFrame();
    expect(result.current.text.length).toBeLessThan(target.length);

    rerender({ done: true });
    expect(result.current).toEqual({ text: target, settled: true });
    expect(frameQueue.size).toBe(0);
  });

  it("shows the full text without animation under reduced motion", () => {
    reducedMotion.value = true;
    const target = "减弱动效直接显示";
    const { result } = renderHook(() => useSmoothText(target, false));
    expect(result.current).toEqual({ text: target, settled: true });
    expect(frameQueue.size).toBe(0);
  });

  it("cancels the pending animation frame on unmount", () => {
    const { unmount } = renderHook(() => useSmoothText("字".repeat(100), false));
    expect(frameQueue.size).toBe(1);
    unmount();
    expect(frameQueue.size).toBe(0);
  });
});
