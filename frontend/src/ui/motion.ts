import type { Transition } from "motion/react";

/** Amicro 风格的入场过渡：轻微上移 + 淡入，硬件加速且尊重系统减弱动效设置。 */
export const fadeUpTransition: Transition = {
  duration: 0.38,
  ease: [0.21, 0.47, 0.32, 0.98],
};

export function fadeUpProps(delay = 0) {
  return {
    initial: { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    transition: { ...fadeUpTransition, delay },
  } as const;
}

export { motion } from "motion/react";
