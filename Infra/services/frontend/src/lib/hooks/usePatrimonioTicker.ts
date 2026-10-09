import { useEffect, useRef, useState } from "react";

// 1% a.m. ÷ seconds per month (30.44 days average)
const SECONDS_PER_MONTH = 30.44 * 24 * 3600; // ≈ 2,630,016

export function usePatrimonioTicker(
  baseValue: number,
  options: { animate?: boolean; animDurationMs?: number; ratePerSecond?: number } = {},
) {
  const { animate = true, animDurationMs = 1600 } = options;
  const perSecond = options.ratePerSecond ?? (baseValue * 0.01) / SECONDS_PER_MONTH;
  const [display, setDisplay] = useState(animate ? 0 : baseValue);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!baseValue) return;

    // Throttle: only re-render when the displayed centavos digit would change
    const msPerCentavo = Math.max(1, (0.01 / perSecond) * 1000);
    const throttleMs = Math.min(msPerCentavo, 100);

    if (animate) {
      const start = performance.now();
      let lastRender = 0;

      const countUp = (now: number) => {
        const elapsed = now - start;
        const progress = Math.min(elapsed / animDurationMs, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        setDisplay(baseValue * eased);
        if (progress < 1) {
          rafRef.current = requestAnimationFrame(countUp);
        } else {
          // Phase 2: tick only when value visibly changes
          const tickStart = Date.now();
          const tick = (ts: number) => {
            if (ts - lastRender >= throttleMs) {
              lastRender = ts;
              const secs = (Date.now() - tickStart) / 1000;
              setDisplay(baseValue + secs * perSecond);
            }
            rafRef.current = requestAnimationFrame(tick);
          };
          rafRef.current = requestAnimationFrame(tick);
        }
      };
      rafRef.current = requestAnimationFrame(countUp);
    } else {
      let lastRender = 0;
      const tickStart = Date.now();
      const tick = (ts: number) => {
        if (ts - lastRender >= throttleMs) {
          lastRender = ts;
          const secs = (Date.now() - tickStart) / 1000;
          setDisplay(baseValue + secs * perSecond);
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => cancelAnimationFrame(rafRef.current);
  }, [baseValue, animate, animDurationMs, perSecond]);

  return display;
}
