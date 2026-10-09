import { useEffect, useState } from "react";
import { Logo } from "@/components/site/Logo";
import { GlobePin } from "@/components/GlobePin";
import { usePatrimonioTicker } from "@/lib/hooks/usePatrimonioTicker";
import { usePublicAum } from "@/lib/hooks/usePublicAum";
import { brl } from "@/lib/format";

const SESSION_KEY = "md70_intro_shown";
const ANIM_DURATION_MS = 1400;
const VISIBLE_AFTER_MS = 2800;
const FADE_DURATION_MS = 600;

export function LoadingScreen() {
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    return !sessionStorage.getItem(SESSION_KEY);
  });
  const [fading, setFading] = useState(false);

  const { data: aumData } = usePublicAum();
  const aumCurrent = aumData?.aum_current ?? 0;
  const ratePerSecond = aumData?.rate_per_second;
  const display = usePatrimonioTicker(aumCurrent, {
    animate: visible && aumCurrent > 0,
    animDurationMs: ANIM_DURATION_MS,
    ratePerSecond,
  });

  useEffect(() => {
    if (!visible) return;
    const dismiss = setTimeout(() => {
      setFading(true);
      setTimeout(() => {
        setVisible(false);
        sessionStorage.setItem(SESSION_KEY, "1");
      }, FADE_DURATION_MS);
    }, VISIBLE_AFTER_MS);
    return () => clearTimeout(dismiss);
  }, [visible]);

  if (!visible) return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-ink text-primary-foreground overflow-hidden"
      style={{
        transition: `opacity ${FADE_DURATION_MS}ms ease`,
        opacity: fading ? 0 : 1,
        pointerEvents: fading ? "none" : "auto",
      }}
    >
      {/* Globe */}
      <div className="absolute inset-0 flex items-center justify-center opacity-25 pointer-events-none select-none">
        <GlobePin size={Math.min(window.innerWidth, 700)} dark />
      </div>

      {/* Content */}
      <div className="relative flex flex-col items-center gap-8 px-6 text-center">
        <Logo className="text-primary-foreground opacity-90 scale-150" />

        <div className="mt-4">
          <p className="text-xs uppercase tracking-[0.2em] opacity-50 mb-3">Patrimônio sob gestão</p>
          {aumData ? (
            <p className="font-display text-5xl md:text-7xl tabular-nums tracking-tight">
              {brl(display)}
            </p>
          ) : (
            <div className="h-16 md:h-20 w-64 md:w-80 mx-auto rounded bg-primary-foreground/10 animate-pulse" />
          )}
          <p className="mt-3 text-xs opacity-40 tracking-wider">e crescendo · 1% a.m.</p>
        </div>

        {/* Construction location badge */}
        <div className="flex items-center gap-2 border border-primary-foreground/20 px-4 py-2 text-xs opacity-60">
          <span className="inline-block h-2 w-2 rounded-full bg-[#E8C142] animate-pulse" />
          <span>São Paulo, Brasil · em construção</span>
        </div>
      </div>
    </div>
  );
}
