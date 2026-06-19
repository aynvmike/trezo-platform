"use client";

import { useRef } from "react";

/**
 * DepthTilt — a landmark depth touch. The child surface tilts toward the
 * cursor in 3D (and lifts slightly), giving a tactile, dimensional feel.
 * Disabled gracefully when the pointer leaves; respects reduced motion via
 * the .depth-tilt class transition.
 */
export function DepthTilt({
  children,
  max = 7,
  className = "",
}: {
  children: React.ReactNode;
  max?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  function handleMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!el) return;
    if (document.documentElement.getAttribute("data-lite") === "on") return;
    const rect = el.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    el.style.transform = `perspective(900px) rotateY(${px * max}deg) rotateX(${-py * max}deg) translateY(-3px)`;
  }
  function reset() {
    const el = ref.current;
    if (el) el.style.transform = "perspective(900px) rotateY(0deg) rotateX(0deg) translateY(0)";
  }

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      onMouseLeave={reset}
      className={`depth-tilt ${className}`}
    >
      {children}
    </div>
  );
}
