import type { ReactNode } from "react";
import { MotionConfig } from "motion/react";

export function MotionProviders({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
