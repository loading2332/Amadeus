import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

const MIN_STEP = 2;
const MAX_STEP = 48;
const CATCH_UP_RATIO = 24;

export interface SmoothTextState {
  /** 当前应显示的文本(target 的前缀)。 */
  text: string;
  /** 已追平目标全文。 */
  settled: boolean;
}

/**
 * 将流式目标全文以 rAF 匀速追进的方式逐帧显现:
 * 每帧步进 `clamp(MIN_STEP, remaining / CATCH_UP_RATIO, MAX_STEP)` 字符,
 * buffer 越大追进越快,避免落后目标太多。
 *
 * `done === true` 或系统开启"减弱动态效果"时不做动画,直接整块显示。
 */
export function useSmoothText(target: string, done: boolean): SmoothTextState {
  const reducedMotion = useReducedMotion() ?? false;
  const instant = done || reducedMotion;
  const [visibleLength, setVisibleLength] = useState(0);
  // 防御:target 变短(理论上不发生)时直接对齐。
  const boundedLength = Math.min(visibleLength, target.length);
  const caughtUp = boundedLength >= target.length;

  useEffect(() => {
    if (instant || caughtUp) return;
    let frame = requestAnimationFrame(function tick() {
      setVisibleLength((current) => {
        const bounded = Math.min(current, target.length);
        const remaining = target.length - bounded;
        if (remaining <= 0) return bounded;
        const step = Math.min(MAX_STEP, Math.max(MIN_STEP, Math.ceil(remaining / CATCH_UP_RATIO)));
        return Math.min(target.length, bounded + step);
      });
      frame = requestAnimationFrame(tick);
    });
    // 追平后 caughtUp 翻转触发本效应重启,由 cleanup 取消已排队的下一帧。
    return () => cancelAnimationFrame(frame);
  }, [target, instant, caughtUp]);

  if (instant) return { text: target, settled: true };
  return { text: target.slice(0, boundedLength), settled: caughtUp };
}
