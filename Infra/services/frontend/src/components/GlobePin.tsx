import { useEffect, useRef } from "react";
import createGlobe from "cobe";

// São Paulo, Brazil
const SP_LAT = -23.5505;
const SP_LON = -46.6333;

function toRadians(deg: number) {
  return (deg * Math.PI) / 180;
}

interface GlobePinProps {
  className?: string;
  size?: number;
  dark?: boolean;
}

export function GlobePin({ className, size = 400, dark = true }: GlobePinProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = Math.min(window.devicePixelRatio ?? 1, 2);

    let phi = toRadians(-SP_LON);
    let isDragging = false;
    let lastX = 0;
    // Velocity for momentum after drag release
    let velocityX = 0;
    let lastDragX = 0;
    let lastDragTime = 0;

    const globe = createGlobe(canvas, {
      devicePixelRatio: dpr,
      width: size * dpr,
      height: size * dpr,
      phi,
      theta: toRadians(SP_LAT) * 0.5,
      dark: dark ? 1 : 0,
      diffuse: 1.2,
      mapSamples: 16000,
      mapBrightness: dark ? 6 : 3,
      baseColor: dark ? [0.08, 0.08, 0.1] : [0.9, 0.9, 0.92],
      markerColor: [0.92, 0.76, 0.26],
      glowColor: dark ? [0.15, 0.15, 0.2] : [0.8, 0.8, 0.85],
      markers: [{ location: [SP_LAT, SP_LON], size: 0.08 }],
    });

    let raf = 0;
    const animate = () => {
      if (isDragging) {
        // Drag controls phi directly — no auto-rotation
      } else {
        // Decay momentum then resume slow auto-rotation
        velocityX *= 0.92;
        if (Math.abs(velocityX) < 0.0005) velocityX = 0;
        phi += velocityX || 0.003;
      }
      globe.update({ phi });
      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);

    // --- pointer events (mouse + touch) ---
    const onPointerDown = (e: PointerEvent) => {
      isDragging = true;
      lastX = e.clientX;
      lastDragX = e.clientX;
      lastDragTime = performance.now();
      velocityX = 0;
      canvas.setPointerCapture(e.pointerId);
      canvas.style.cursor = "grabbing";
    };

    const onPointerMove = (e: PointerEvent) => {
      if (!isDragging) return;
      const dx = e.clientX - lastX;
      // Scale: one full canvas width ≈ 2π rotation
      phi -= (dx / size) * Math.PI * 1.5;
      lastX = e.clientX;

      // Track velocity for momentum
      const now = performance.now();
      const dt = now - lastDragTime;
      if (dt > 0) {
        velocityX = -((e.clientX - lastDragX) / size) * Math.PI * 1.5 * (16 / dt);
      }
      lastDragX = e.clientX;
      lastDragTime = now;
    };

    const onPointerUp = () => {
      if (!isDragging) return;
      isDragging = false;
      canvas.style.cursor = "grab";
    };

    canvas.style.cursor = "grab";
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerUp);

    return () => {
      cancelAnimationFrame(raf);
      globe.destroy();
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerUp);
    };
  }, [size, dark]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size }}
      className={className}
    />
  );
}
